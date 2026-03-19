"""
memory_strip.py — Fact extractor for news_memory.txt entries.

Strips emojis, decorative markdown, TNN sign-offs, and narrative fluff
from bulletin text before storing in memory.  The memory file is read back
as context for future bulletin generation, so keeping it lean and factual
improves continuity and prevents the model from echoing filler phrases.

Used by news_feed._write_memory() and can be run standalone to clean
the existing news_memory.txt file:

    python -m src.memory_strip          # dry-run (prints cleaned entries)
    python -m src.memory_strip --apply  # overwrites news_memory.txt
"""

from __future__ import annotations
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Emoji removal
# ---------------------------------------------------------------------------

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF\U0001FA00-\U0001FA6F\U0001FA70-\U0001FAFF"
    "\U00002702-\U000027B0\U000024C2-\U0001F251"
    "\U0000FE0F\U0000200D\U00002600-\U000026FF"
    "\U00002B50-\U00002B55\U0000231A-\U0000231B"
    "\U000023CF\U000023E9-\U000023F3\U000023F8-\U000023FA"
    "]+", flags=re.UNICODE
)

# ---------------------------------------------------------------------------
# Pass 1: patterns that rely on markdown formatting still being present
# ---------------------------------------------------------------------------

_FLUFF_PASS1 = [
    re.compile(r"^-#\s.*$", re.MULTILINE),                                       # TNN sign-offs
    re.compile(r"^\*\*(?:Undercity Dispatch|Tower Authority Alert)[^*]*\*\*\s*$", re.MULTILINE),
    re.compile(r"^\*\*[^*]{3,80}\*\*\s*$", re.MULTILINE),                        # bold location headers
    re.compile(r"^\*[^*]{5,120}\*\s*$", re.MULTILINE),                            # italic headlines
]

# ---------------------------------------------------------------------------
# Pass 2: patterns that run on clean (markdown-stripped) prose
# ---------------------------------------------------------------------------

_FLUFF_PASS2 = [
    # Sentence-level removals
    re.compile(r"Will\s+.{10,150}\?", re.IGNORECASE),
    re.compile(r"The people (?:watch|whisper|wonder|gather)[^.]*\.\s*", re.IGNORECASE),
    re.compile(r"[Ww]hispers of [^.]{5,80}(?:ripple|mingle|fill)[^.]*\.\s*"),
    re.compile(r"[Aa]\s+(?:tense|hushed|eerie|chilling)\s+(?:hush|silence|pall)\s+(?:descends|falls|hangs)[^.]*\.\s*"),
    re.compile(r"A hush falls over [^.]*[.,]\s*", re.IGNORECASE),
    re.compile(r"Their faces reflect[^.]*\.\s*", re.IGNORECASE),
    re.compile(r"A (?:loud|deafening)\s+\w+\s+echoes[^.]*\.\s*", re.IGNORECASE),
    # Phrase-level removals
    re.compile(r"The city(?:'s eyes fall on| watches| pulses),?\s*", re.IGNORECASE),
    re.compile(r"The crowd holds its breath,?\s*", re.IGNORECASE),
    re.compile(r"The whispers of the crowd rise,?\s*", re.IGNORECASE),
    re.compile(r",?\s*whispers of [^.]{3,60}mingling[^,.]*[.,]?\s*", re.IGNORECASE),
    re.compile(r",?\s*(?:their|her|his) eyes (?:reflecting|flickering|narrowing|shining|widening|lighting|focused|darting|locked)[^,.]*", re.IGNORECASE),
    re.compile(r",?\s*casting\s+(?:a\s+)?(?:eerie|long|dark|chilling)\s+(?:shadows?|pall)[^,.]*", re.IGNORECASE),
    re.compile(r",?\s*a frown creasing (?:his|her) brow", re.IGNORECASE),
    re.compile(r",?\s*the room falling silent[^,.]*", re.IGNORECASE),
    # Opener strippers
    re.compile(r"As the (?:sun|moon|dawn|dusk)[^,]{5,60},\s*", re.IGNORECASE),
    re.compile(r"As dawn breaks over the city,\s*", re.IGNORECASE),
    re.compile(r"In the moonlit shadows of [^,]{3,40},\s*", re.IGNORECASE),
    re.compile(r"As shadows dance[^,.]*[.,]\s*", re.IGNORECASE),
]


def strip_to_facts(text: str) -> str:
    """Strip emojis, decorative markdown, and narrative fluff from a bulletin.
    Returns a compact factual summary suitable for memory storage."""

    s = text.strip()
    if s.startswith("[") and s.endswith("]"):
        return s

    # 1. Emojis
    text = _EMOJI_RE.sub("", text)

    # 2. Pass 1 — strip while markdown is intact
    for pat in _FLUFF_PASS1:
        text = pat.sub("", text)

    # 3. Strip markdown: **bold** -> bold, *italic* -> italic
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)

    # 4. Pass 2 — strip on clean prose
    for pat in _FLUFF_PASS2:
        text = pat.sub("", text)

    # 5. Collapse to single line
    lines = [l.strip() for l in text.splitlines()
             if l.strip() and l.strip() not in ("**", "*", "---", "\u2014", "-#")]
    result = " ".join(lines)

    # 6. Post-cleanup
    result = re.sub(r"\bas as\b", "as", result)
    result = re.sub(r"(?<=[.!]) as\b", "", result)
    result = re.sub(r"\.as\b", ".", result)
    result = re.sub(r"^as\s+", "", result, flags=re.IGNORECASE)
    result = re.sub(r",\s*as\s*[,.]", ".", result)
    result = re.sub(r"Tensions simmer, as\b.*", "Tensions simmer.", result)
    result = re.sub(r",\s*,", ",", result)
    result = re.sub(r"\.\s*\.", ".", result)
    result = re.sub(r",\s*\.", ".", result)
    result = re.sub(r"  +", " ", result)
    result = re.sub(r"^[,.\s]+", "", result)
    result = re.sub(r"\s+or\.\s*$", ".", result)
    result = re.sub(r"\s+or\s*$", ".", result)
    result = result.strip().rstrip(",")
    if result and not result.endswith("."):
        result += "."
    if result and result[0].islower():
        result = result[0].upper() + result[1:]
    return result


# ---------------------------------------------------------------------------
# Standalone CLI: clean the existing news_memory.txt
# ---------------------------------------------------------------------------

def clean_memory_file(memory_path: Path, *, apply: bool = False) -> str:
    """Read news_memory.txt, strip every entry, optionally overwrite."""
    if not memory_path.exists():
        return "File not found."

    raw = memory_path.read_text(encoding="utf-8", errors="ignore")
    entries = [e.strip() for e in raw.split("\n---ENTRY---\n") if e.strip()]

    cleaned = []
    for entry in entries:
        parts = entry.split("\n", 1)
        if len(parts) == 2 and parts[0].startswith("["):
            ts, body = parts[0], strip_to_facts(parts[1])
        else:
            ts, body = "", strip_to_facts(entry)
        if body and body != ".":
            cleaned.append(f"{ts}\n{body}" if ts else body)

    output = "\n---ENTRY---\n".join(cleaned)

    if apply:
        memory_path.write_text(output, encoding="utf-8")

    return (
        f"Entries: {len(entries)} -> {len(cleaned)}\n"
        f"Size: {len(raw)} -> {len(output)} bytes "
        f"({100 - len(output) * 100 // max(len(raw), 1)}% reduction)"
    )


if __name__ == "__main__":
    import sys
    docs = Path(__file__).resolve().parent.parent / "campaign_docs"
    mem  = docs / "news_memory.txt"
    do_apply = "--apply" in sys.argv
    print(clean_memory_file(mem, apply=do_apply))
    if not do_apply:
        print("(dry run — use --apply to overwrite)")
