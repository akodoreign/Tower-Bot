"""
src/bulletin_cleaner.py — Post-processing for LLM-generated news bulletins.

Aggressively strips:
- LLM reasoning and commentary that leaks into output
- Invalid EC (Essence Coin) references
- Truncated or malformed content

Usage:
    from src.bulletin_cleaner import clean_bulletin, validate_bulletin

    # Clean raw LLM output
    cleaned = clean_bulletin(raw_output)

    # Validate content meets minimum requirements
    is_valid, reason = validate_bulletin(cleaned)
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM Reasoning Patterns — things that should NEVER appear in output
# ---------------------------------------------------------------------------

# Patterns that indicate LLM is explaining its work instead of outputting content
_LLM_REASONING_PATTERNS = [
    # Bullet points with editing notes
    re.compile(r'^[-•*]\s*(?:Added|Removed|Changed|Adjusted|Fixed|Corrected|Updated|Modified|Replaced|Tone|Style|Formatting|Length|Continuity|Note|Edit|Change)[^.]*\.?\s*$', re.IGNORECASE | re.MULTILINE),
    # Lines starting with editing keywords
    re.compile(r'^(?:Formatting adjustments?|Tone/Style|Changes made|Edits?|Notes?|Corrections?|Adjustments?|Revisions?)[:\s].*$', re.IGNORECASE | re.MULTILINE),
    # Lines explaining what was done
    re.compile(r'^[-•*]?\s*(?:I (?:have |)(?:added|removed|changed|fixed|adjusted|corrected|updated|modified|replaced)|This (?:was|is|has been) (?:added|removed|changed|fixed|adjusted|corrected|updated|modified|replaced)).*$', re.IGNORECASE | re.MULTILINE),
    # Numbered edit explanations (1. "old" → "new": reason)
    re.compile(r'^\d+\.\s*["\'][^"\']+["\']?\s*[→→=>\-]+\s*["\']?[^"\']*["\']?\s*:?\s*[-–—]?\s*.*$', re.IGNORECASE | re.MULTILINE),
    # Lines with arrow transformations showing edits
    re.compile(r'^.*["\'][^"\']+["\'].*(?:→|->|=>|replaced with|changed to).*["\'][^"\']+["\'].*$', re.IGNORECASE | re.MULTILINE),
    # Lines explaining rationale
    re.compile(r'^[-•*]?\s*(?:The (?:previous|original|draft)|As per|According to|To (?:maintain|ensure|align)|For (?:clarity|consistency|tone)).*$', re.IGNORECASE | re.MULTILINE),
    # Preamble lines
    re.compile(r'^(?:Here\'?s?|Below is|The following|This is|I\'?ve|Certainly|Sure|Of course|Absolutely|As requested).*:?\s*$', re.IGNORECASE | re.MULTILINE),
    # Meta-commentary about the bulletin
    re.compile(r'^[-•*]?\s*(?:This bulletin|The bulletin|This story|The story|This report).*(?:maintains|preserves|aligns|follows|reflects).*$', re.IGNORECASE | re.MULTILINE),
    # Lines with (e.g., or (as per
    re.compile(r'^.*\((?:e\.g\.|as per|per the|following the|in line with).*\).*$', re.IGNORECASE | re.MULTILINE),
    # Lines that start with a dash and contain editing language
    re.compile(r'^-\s*(?:Retained|Preserved|Maintained|Ensured|Kept|Added|Updated).*$', re.IGNORECASE | re.MULTILINE),
]

# Standalone phrases that are editor commentary, not content
_EDITOR_PHRASES = [
    "formatting adjustments",
    "formatting adjustment",
    "tone/style",
    "tone adjustment",
    "style adjustment",
    "length adjustment",
    "continuity check",
    "continuity with",
    "no new facts",
    "core narrative",
    "retained the",
    "tightened the",
    "enhanced the",
    "preserved the",
    "aligned with",
    "per formatting guidelines",
    "as per formatting",
    "for visual emphasis",
    "to enhance",
    "to maintain",
    "to ensure",
    "to align",
    "without inventing",
    "inventing new facts",
    "aligning with the established",
    "references the",
    "established narrative",
    "original structure",
    "descriptive detail",
]

# Preamble phrases to strip from start of output
_PREAMBLE_PHRASES = (
    "sure", "here's", "here is", "certainly", "of course",
    "below is", "as requested", "i hope", "absolutely",
    "corrected", "the corrected", "here you go", "fixed",
    "revised", "updated", "edited",
)


def strip_llm_reasoning(text: str) -> str:
    """
    Aggressively strip LLM reasoning, commentary, and editing notes from output.
    This catches cases where the model explains what it changed instead of just
    outputting the corrected content.
    """
    if not text:
        return text

    original = text

    # Apply regex patterns to remove reasoning lines
    for pattern in _LLM_REASONING_PATTERNS:
        text = pattern.sub('', text)

    # Remove lines containing editor phrases
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        line_lower = line.lower().strip()

        # Keep empty lines for now (we'll clean them up later)
        if not line_lower:
            cleaned_lines.append(line)
            continue

        # Check if line contains editor commentary
        if any(phrase in line_lower for phrase in _EDITOR_PHRASES):
            logger.debug(f"Stripped editor phrase line: {line[:60]}...")
            continue

        # Skip lines that are just bullet points with editing notes
        if line_lower.startswith(('-', '•', '*')) and len(line_lower) < 120:
            edit_indicators = [
                'added', 'removed', 'changed', 'fixed', 'adjusted',
                'corrected', 'updated', 'modified', 'replaced',
                'tone', 'style', 'format', 'length', 'retained',
                'preserved', 'maintained', 'ensured', 'enhanced',
            ]
            if any(ind in line_lower for ind in edit_indicators):
                logger.debug(f"Stripped edit indicator line: {line[:60]}...")
                continue

        cleaned_lines.append(line)

    text = '\n'.join(cleaned_lines)

    # Strip preamble lines from start
    lines = text.splitlines()
    while lines and lines[0].lower().strip().rstrip("!:,.").startswith(_PREAMBLE_PHRASES):
        logger.debug(f"Stripped preamble: {lines[0][:60]}...")
        lines.pop(0)

    # Strip trailing metadata/commentary
    while lines and lines[-1].lower().strip().startswith(("note:", "notes:", "changes:", "edits:", "i ", "-", "•", "*")):
        logger.debug(f"Stripped trailing: {lines[-1][:60]}...")
        lines.pop()

    text = '\n'.join(lines)

    # Clean up multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()

    if text != original:
        logger.info("📰 Stripped LLM reasoning from bulletin output")

    return text


# ---------------------------------------------------------------------------
# EC (Essence Coin) Filtering
# ---------------------------------------------------------------------------

# Catch ALL "X EC" patterns
_EC_MENTION_PATTERN = re.compile(r'\b(\d[\d,]*)\s*EC\b', re.IGNORECASE)

# Patterns that are ALLOWED (actual purchases with context)
_EC_ALLOWED_CONTEXTS = [
    # "costs X EC" or "cost X EC"
    re.compile(r'costs?\s+\d[\d,]*\s*EC\b', re.IGNORECASE),
    # "for X EC" when preceded by sell/buy verbs
    re.compile(r'(?:sold|bought|purchased|sells?|buys?|selling|buying)\s+(?:a|an|the|some|her|his|their)?\s*\w+(?:\s+\w+){0,3}?\s+for\s+\d[\d,]*\s*EC\b', re.IGNORECASE),
    # "X EC each" for items with price context
    re.compile(r'(?:at|for|costs?|priced|valued)\s+\d[\d,]*\s*EC\s+each\b', re.IGNORECASE),
    # "paid X EC for"
    re.compile(r'paid\s+\d[\d,]*\s*EC\s+for\b', re.IGNORECASE),
    # "stole X EC" (actual currency theft)
    re.compile(r'stole\s+\d[\d,]*\s*EC\b', re.IGNORECASE),
    # "owes X EC" (debt)
    re.compile(r'owes?\s+(?:the\s+\w+\s+)?\d[\d,]*\s*EC\b', re.IGNORECASE),
    # "worth X EC" for item valuation
    re.compile(r'worth\s+\d[\d,]*\s*EC\b', re.IGNORECASE),
]

# Patterns that are NEVER allowed (abuse patterns)
_EC_ABUSE_PATTERNS = [
    re.compile(r'\d+\s*EC\s+per\s+(?:person|life|soul|head|body|victim)', re.IGNORECASE),
    re.compile(r'\d+\s*EC\s+in\s+(?:shattered|broken|spilled|lost|scattered|wasted|burning|fading|dying)', re.IGNORECASE),
    re.compile(r'\d+\s*EC\s+from\s+(?:their|her|his|fingertips?|hands?|eyes?|tears?|blood)', re.IGNORECASE),
    re.compile(r'(?:bleeding|bleeds?)\s+(?:\d+\s*)?EC', re.IGNORECASE),
    re.compile(r'EC\s+(?:bleeds?|bleeding)', re.IGNORECASE),
    re.compile(r'(?:the\s+)?weight\s+of\s+\d+\s*EC', re.IGNORECASE),
    re.compile(r'\d+\s*EC\s+worth\s+of\s+(?:despair|hope|fear|chaos|desperation|suffering|pain|sorrow)', re.IGNORECASE),
    re.compile(r'\d+\s*EC\s+(?:reward|bounty|incentive|fee)\s+for\s+(?:info|information|evidence|shard|ledger)', re.IGNORECASE),
    re.compile(r'\d+\s*EC\s+increments?', re.IGNORECASE),
    re.compile(r'smuggle[ds]?\s+EC|smuggled?\s+(?:the\s+)?EC', re.IGNORECASE),
    re.compile(r'trading\s+(?:in\s+)?EC', re.IGNORECASE),
    re.compile(r'recovery\s+costs?\s+in\s+\d+\s*EC', re.IGNORECASE),
    re.compile(r'\d+\s*EC\s+of\s+(?:despair|hope|fear|chaos|desperation|suffering|pain|sorrow|silence|darkness)', re.IGNORECASE),
]


def filter_ec_references(text: str) -> str:
    """
    Filter out invalid EC references.
    Keeps valid purchase/transaction EC references, removes:
    - Metaphorical EC usage
    - EC as rewards/bounties (should be Kharma)
    - Random EC amounts without purchase context
    """
    if not text or 'EC' not in text.upper():
        return text

    original = text

    # First, remove definitely abusive patterns
    for pattern in _EC_ABUSE_PATTERNS:
        text = pattern.sub('', text)

    # Check if any remaining EC mention matches an allowed pattern
    if _EC_MENTION_PATTERN.search(text):
        has_valid_ec = any(pat.search(text) for pat in _EC_ALLOWED_CONTEXTS)

        if not has_valid_ec:
            # No valid EC usage found — strip ALL EC mentions
            text = _EC_MENTION_PATTERN.sub('', text)
            text = re.sub(r'\b(?:essence\s+coins?)\b', '', text, flags=re.IGNORECASE)

    # Clean up orphaned punctuation and whitespace
    # Only collapse within-line whitespace — preserve newlines
    text = re.sub(r'[^\S\n]+', ' ', text)
    text = re.sub(r'[^\S\n]+([,.])', r'\1', text)
    text = re.sub(r'([,.]){2,}', r'\1', text)
    text = re.sub(r'^\s*[,.]\s*', '', text, flags=re.MULTILINE)
    text = text.strip()

    if text != original:
        logger.info("📰 Filtered EC references from bulletin")

    return text


# ---------------------------------------------------------------------------
# Truncation Detection
# ---------------------------------------------------------------------------

def is_truncated(text: str) -> bool:
    """
    Check if text appears to be truncated mid-generation.
    Returns True if the text shows signs of being cut off.
    """
    if not text:
        return True
    
    text = text.strip()
    
    # Check for obvious truncation patterns
    truncation_endings = [
        '...',           # Explicit truncation
        '…',             # Unicode ellipsis
    ]
    for ending in truncation_endings:
        if text.endswith(ending):
            return True
    
    # Check if ends with comma/semicolon/colon (mid-sentence)
    if re.search(r'[,;:]\s*$', text):
        return True
    
    # Check if ends with a conjunction/preposition/determiner (mid-sentence)
    incomplete_words = [
        'and', 'but', 'or', 'the', 'a', 'an', 'to', 'of', 'in', 'for',
        'with', 'on', 'at', 'by', 'from', 'as', 'is', 'was', 'were',
        'are', 'be', 'been', 'being', 'have', 'has', 'had', 'that',
        'which', 'who', 'whom', 'whose', 'when', 'where', 'why', 'how',
    ]
    last_word = text.split()[-1].lower().rstrip('.,!?;:') if text.split() else ''
    if last_word in incomplete_words:
        return True
    
    # Check if last sentence appears incomplete (no period, question mark, or exclamation)
    # But allow for TNN signoffs which start with -#
    lines = text.splitlines()
    last_content_line = None
    for line in reversed(lines):
        line = line.strip()
        if line and not line.startswith('-#'):
            last_content_line = line
            break
    
    if last_content_line:
        # Must end with sentence-ending punctuation or markdown formatting
        if not re.search(r'[.!?\*"]\s*$', last_content_line):
            return True
    
    return False


# ---------------------------------------------------------------------------
# Content Validation
# ---------------------------------------------------------------------------

MIN_BULLETIN_LINES = 2
MIN_BULLETIN_CHARS = 80
MIN_BULLETIN_WORDS = 15


def validate_bulletin(text: str) -> tuple[bool, str]:
    """
    Validate that a bulletin has enough content to be posted.
    Returns (is_valid, reason).

    A valid bulletin must have:
    - At least 2 content lines (excluding the TNN signoff)
    - At least 80 characters of content
    - At least 15 words
    - No incomplete sentences (ending with "demanded." with no object)
    - Not be truncated mid-generation
    """
    if not text:
        return False, "empty"

    # Check for truncation first
    if is_truncated(text):
        return False, "truncated"

    # Strip TNN signoff for validation
    lines = text.strip().splitlines()
    content_lines = [ln for ln in lines if not ln.strip().startswith('-#')]

    # Check line count
    non_empty_lines = [ln for ln in content_lines if ln.strip()]
    if len(non_empty_lines) < MIN_BULLETIN_LINES:
        return False, f"too few lines ({len(non_empty_lines)})"

    content = '\n'.join(content_lines)

    # Check character count
    if len(content) < MIN_BULLETIN_CHARS:
        return False, f"too short ({len(content)} chars)"

    # Check word count
    words = content.split()
    if len(words) < MIN_BULLETIN_WORDS:
        return False, f"too few words ({len(words)})"

    # Check for incomplete sentences (reuses the shared pattern list)
    for pat in _INCOMPLETE_SENTENCE_PATTERNS:
        if re.search(pat, content, re.IGNORECASE | re.MULTILINE):
            return False, "incomplete sentence"

    return True, "valid"


# ---------------------------------------------------------------------------
# Main Cleaning Function
# ---------------------------------------------------------------------------

def clean_bulletin(text: str) -> str:
    """
    Apply all cleaning steps to raw LLM bulletin output.
    Returns cleaned text ready for validation.
    
    Order of operations:
    1. Strip LLM reasoning and commentary
    2. Filter invalid EC references
    3. Clean up whitespace
    """
    if not text:
        return text

    # Step 1: Strip LLM reasoning
    text = strip_llm_reasoning(text)

    # Step 2: Filter EC references
    text = filter_ec_references(text)

    # Step 3: Final whitespace cleanup (preserve newlines)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[^\S\n]{2,}', ' ', text)
    text = text.strip()

    return text


_INCOMPLETE_SENTENCE_PATTERNS = [
    r'\b(?:demanded|demands)\s*\.\s*$',
    r'\b(?:sold|bought|costs?|sells?)\s*\.\s*$',
    r'(?:for|at|with|to|from|of|in|and|but|or|the|a|an|by|as|is|was)\s*\.\s*$',
    r'\bthe\s+\.\s*$',
    r'\ba\s+\.\s*$',
    r'\ban\s+\.\s*$',
    r'"\s*\.\s*$',
]


def _sentence_is_complete(s: str) -> bool:
    """Return True if a sentence fragment ends cleanly (no incomplete patterns)."""
    s = s.strip()
    if not re.search(r'[.!?\"]\s*$', s):
        return False
    for pat in _INCOMPLETE_SENTENCE_PATTERNS:
        if re.search(pat, s, re.IGNORECASE | re.MULTILINE):
            return False
    return True


def repair_incomplete_bulletin(text: str) -> str:
    """
    Attempt to salvage a bulletin that ends mid-sentence.

    Strategy (preserves original line structure):
    1. Separate the TNN -# signoff lines from the body.
    2. Work backwards through content lines dropping any trailing incomplete line.
    3. Re-attach the signoff.

    If the bulletin is a single line with no complete sentence to fall back to,
    returns the original unchanged (caller will then discard it).
    """
    if not text:
        return text

    lines = text.strip().splitlines()

    # Peel off trailing -# signoff lines
    suffix_lines: list[str] = []
    while lines and lines[-1].strip().startswith("-#"):
        suffix_lines.insert(0, lines.pop())

    # Remove trailing blank lines from body
    while lines and not lines[-1].strip():
        lines.pop()

    if not lines:
        return text

    # Walk backwards dropping lines that are incomplete
    while lines:
        last_line = lines[-1].strip()
        if _sentence_is_complete(last_line):
            break
        lines.pop()  # drop incomplete trailing line

    if not lines:
        # Nothing left — original is unrecoverable
        return text

    body = "\n".join(lines)
    if suffix_lines:
        body = body + "\n" + "\n".join(suffix_lines)
    return body


def clean_and_validate(text: str) -> tuple[str | None, str]:
    """
    Clean bulletin and validate it.
    Returns (cleaned_text, status).
    If invalid, returns (None, reason).
    """
    cleaned = clean_bulletin(text)
    is_valid, reason = validate_bulletin(cleaned)

    if is_valid:
        return cleaned, "valid"
    else:
        logger.warning(f"📰 Bulletin failed validation: {reason}")
        return None, reason
