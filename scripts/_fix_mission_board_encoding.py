"""Fix remaining mojibake in src/mission_board.py - pass 2."""
from __future__ import annotations
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FILE = ROOT / "src" / "mission_board.py"

# All broken strings expressed as Unicode escapes (safe in any encoding)
EXACT = [
    # BOM
    ("﻿", ""),
    # left/right curly single quotes
    ("â€˜", "‘"),   # â€˜ -> '
    ("â€™", "’"),   # â€™ -> '
    # left/right curly double quotes
    ("â€œ", "“"),   # â€œ -> "
    ("â€", "”"),          # â€ -> "  (must come AFTER â€œ and â€")
    # em dash
    ("â€“", "—"),   # â€" -> —
    # en dash
    ("â€”", "–"),   # â€" -> –
    # bullet
    ("â€¢", "•"),   # â€¢ -> •
    # ellipsis
    ("â€¦", "…"),   # â€¦ -> …
    # approximately equal
    ("â‰ˆ", "≈"),   # â‰ˆ -> ≈
    # middle dot / interpunct
    ("Â·", "·"),          # Â· -> ·
    # non-breaking space
    ("Â ", " "),          # Â  -> NBSP
    # multiplication sign
    ("Ã—", "×"),          # Ã— -> ×
]


def fix(path: Path) -> None:
    from src.text_mojibake import repair_mojibake, _MOJIBAKE_MARKERS

    text = path.read_text(encoding="utf-8")
    original = text

    # Pass 1: targeted exact replacements (cp1252-path mojibake)
    changed = 0
    for broken, correct in EXACT:
        n = text.count(broken)
        if n:
            text = text.replace(broken, correct)
            changed += n
    print(f"  Exact replacements: {changed}")

    # Pass 2: repair_mojibake line-by-line (Latin-1 path, remaining emoji)
    lines_fixed = 0
    out = []
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\n\r")
        if any(m in bare for m in _MOJIBAKE_MARKERS):
            fixed = repair_mojibake(bare)
            if fixed != bare:
                lines_fixed += 1
                out.append(fixed + line[len(bare):])
                continue
        out.append(line)
    text = "".join(out)
    print(f"  repair_mojibake: {lines_fixed} lines fixed")

    remaining = [(m[:8], text.count(m)) for m in _MOJIBAKE_MARKERS if m in text]
    if remaining:
        print(f"  Still remaining: {remaining}")
    else:
        print("  No mojibake markers remain.")

    if text == original:
        print("No changes made.")
        return

    path.write_text(text, encoding="utf-8")
    print(f"Wrote {path}")


if __name__ == "__main__":
    fix(FILE)
    print("Done.")
