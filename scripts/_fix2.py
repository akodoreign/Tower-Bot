"""Fix remaining broken emoji sequences in mission_board.py."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
f = ROOT / "src" / "mission_board.py"
src = f.read_text(encoding="utf-8")
orig = src

# broken string (in file) -> correct Unicode (as escape so this script is safe in cp1252)
FIXES = [
    ("\xe2\x9a\xaa",       "⚪"),   # white circle U+26AA
    ("\xe2\x9a\xa1",       "⚡"),   # lightning bolt U+26A1
    ("\xe2\x9c\x93",       "✓"),   # check mark U+2713
    ("\xe2\x95\x90",       "═"),   # box drawing double horizontal U+2550
]

# Re-express using Python's string: decode cp1252 bytes to get the mojibake chars
def moji(b):
    return bytes(b).decode("cp1252", errors="replace")

FIXES2 = [
    (moji([0xE2, 0x9A, 0xAA]), "⚪"),
    (moji([0xE2, 0x9A, 0xA1]), "⚡"),
    (moji([0xE2, 0x9C, 0x93]), "✓"),
    (moji([0xE2, 0x95, 0x90]), "═"),
]

changed = 0
for broken, correct in FIXES2:
    n = src.count(broken)
    if n:
        src = src.replace(broken, correct)
        changed += n
        print(f"Fixed {n}x  len={len(broken)}")

if src != orig:
    f.write_text(src, encoding="utf-8")
    print(f"Done. {changed} replacements.")
else:
    print("No changes.")
