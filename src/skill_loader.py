"""Skill Loader — reads skill records from MySQL (falls back to campaign_docs/skills/).

Each skill has a YAML-like header with:
  - **Keywords:** comma-separated relevance keywords
  - **Category:** lore | systems | rules | persona | style | learned
  - **Version:** integer version number
  - **Source:** seed | self-learned | dm-edited

The loader scores each skill against the user's message using keyword
overlap and returns the top-N most relevant skill bodies to inject into
the system prompt.
"""

import re
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, field
from src.log import logger

# ── Paths (kept for file fallback + write-through) ─────────────────────

SKILLS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs" / "skills"

# ── Data model ─────────────────────────────────────────────────────────

@dataclass
class Skill:
    """A single loaded skill with its metadata and body."""
    filename: str
    title: str
    keywords: List[str]
    category: str
    version: int
    source: str
    body: str

    _keyword_set: set = field(default_factory=set, repr=False)

    def __post_init__(self):
        self._keyword_set = {k.strip().lower() for k in self.keywords if k.strip()}


# ── Cache ──────────────────────────────────────────────────────────────

_skills_cache: Optional[List[Skill]] = None
_cache_ts: float = 0.0   # when cache was last populated


def _row_to_skill(row: dict) -> Skill:
    text = row.get("body") or ""
    keywords_raw = row.get("keywords") or ""
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    return Skill(
        filename=row.get("filename", ""),
        title=row.get("title") or row.get("filename", ""),
        keywords=keywords,
        category=row.get("category") or "unknown",
        version=int(row.get("version") or 1),
        source=row.get("source") or "unknown",
        body=text,
        _keyword_set=set(),
    )


def _parse_skill_text(text: str, filename: str) -> Optional[Skill]:
    """Parse a skill markdown body into a Skill (used for file fallback)."""
    def _ex(pat, default=""):
        m = re.search(pat, text, re.IGNORECASE)
        return m.group(1).strip() if m else default

    keywords_raw = _ex(r"\*\*Keywords?:\*\*\s*(.+)")
    category     = _ex(r"\*\*Category:\*\*\s*(\S+)", "unknown")
    version_str  = _ex(r"\*\*Version:\*\*\s*(\d+)", "1")
    source       = _ex(r"\*\*Source:\*\*\s*(\S+)", "unknown")
    title_m      = re.search(r"^#\s+(?:Skill:\s*)?(.+)", text, re.MULTILINE)
    title        = title_m.group(1).strip() if title_m else filename.replace(".md", "")
    keywords     = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    return Skill(
        filename=filename,
        title=title,
        keywords=keywords,
        category=category,
        version=int(version_str),
        source=source,
        body=text,
        _keyword_set=set(),
    )


def load_skills(force: bool = False) -> List[Skill]:
    """Load all skills from MySQL, falling back to campaign_docs/skills/ files."""
    global _skills_cache, _cache_ts
    import time

    if not force and _skills_cache is not None and (time.time() - _cache_ts) < 300:
        return _skills_cache

    # Primary: MySQL
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT filename, title, keywords, category, version, source, body FROM skills ORDER BY filename") or []
        if rows:
            skills = [_row_to_skill(r) for r in rows]
            _skills_cache = skills
            _cache_ts = time.time()
            logger.info(f"🧠 skill_loader: loaded {len(skills)} skills from DB")
            return skills
    except Exception as e:
        logger.warning(f"skill_loader: DB load failed: {e}")

    # Fallback: files
    if not SKILLS_DIR.exists():
        _skills_cache = []
        return []

    skills = []
    for filepath in sorted(SKILLS_DIR.glob("*.md")):
        try:
            text = filepath.read_text(encoding="utf-8")
            skill = _parse_skill_text(text, filepath.name)
            if skill:
                skills.append(skill)
        except Exception as e:
            logger.warning(f"skill_loader: cannot read {filepath.name}: {e}")

    _skills_cache = skills
    import time as _t; _cache_ts = _t.time()
    logger.info(f"🧠 skill_loader: loaded {len(skills)} skills from files (DB unavailable)")
    return skills


def save_skill_to_db(skill_text: str, filename: str) -> bool:
    """
    Write a skill to MySQL (and keep the file in sync).
    Called by self_learning._save_learned_skill().
    Returns True on success.
    """
    skill = _parse_skill_text(skill_text, filename)
    if not skill:
        return False
    try:
        from src.db_api import raw_execute as _rx
        _rx(
            """INSERT INTO skills (filename, title, keywords, category, version, source, body)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE title=%s, keywords=%s, category=%s,
               version=%s, source=%s, body=%s, updated_at=NOW()""",
            (skill.filename, skill.title, ",".join(skill.keywords), skill.category,
             skill.version, skill.source, skill_text,
             skill.title, ",".join(skill.keywords), skill.category,
             skill.version, skill.source, skill_text)
        )
        # Invalidate cache
        global _skills_cache; _skills_cache = None
        # Write-through to file
        try:
            SKILLS_DIR.mkdir(parents=True, exist_ok=True)
            (SKILLS_DIR / filename).write_text(skill_text, encoding="utf-8")
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error(f"skill_loader: save_skill_to_db error: {e}")
        return False


# ── Tokenize ──────────────────────────────────────────────────────────

def _tokenize(text: str) -> set:
    """Simple tokenizer: lowercase alphanumeric words."""
    return set(re.findall(r"\w+", text.lower()))


# ── Scoring ───────────────────────────────────────────────────────────

def score_skill(skill: Skill, query_tokens: set) -> float:
    score = 0.0
    for kw in skill._keyword_set:
        if kw in query_tokens:
            score += 2.0
        else:
            for qt in query_tokens:
                if kw in qt or qt in kw:
                    score += 0.5
                    break
    if skill.category.lower() in query_tokens:
        score += 1.0
    return score


def match_skills(
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    top_n: int = 3,
    min_score: float = 1.0,
) -> List[Skill]:
    skills = load_skills()
    if not skills:
        return []

    query_text = user_message
    if conversation_history:
        for msg in conversation_history[-6:]:
            if msg.get("role") == "user":
                query_text += " " + msg.get("content", "")

    query_tokens = _tokenize(query_text)

    scored: List[Tuple[float, Skill]] = []
    for skill in skills:
        s = score_skill(skill, query_tokens)
        if s >= min_score:
            scored.append((s, skill))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [skill for _, skill in scored[:top_n]]


def format_skills_for_prompt(skills: List[Skill], max_chars: int = 4000) -> str:
    if not skills:
        return ""

    parts = ["[TOWER SKILLS — Relevant Knowledge]"]
    total = len(parts[0])

    for skill in skills:
        block = f"\n\n--- {skill.title} (v{skill.version}) ---\n{skill.body}"
        if total + len(block) > max_chars:
            remaining = max_chars - total - 50
            if remaining > 200:
                parts.append(f"\n\n--- {skill.title} (v{skill.version}) [truncated] ---\n{skill.body[:remaining]}...")
            break
        parts.append(block)
        total += len(block)

    return "\n".join(parts)


# ── Inventory ──────────────────────────────────────────────────────────

def get_skill_inventory() -> List[Dict]:
    skills = load_skills()
    return [
        {
            "title": s.title,
            "filename": s.filename,
            "category": s.category,
            "version": s.version,
            "source": s.source,
            "keywords": s.keywords[:8],
        }
        for s in skills
    ]


def get_skill_body(filename: str) -> Optional[str]:
    skills = load_skills()
    for s in skills:
        if s.filename == filename:
            return s.body
    return None
