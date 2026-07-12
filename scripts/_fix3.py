"""Fix curly quotes -> straight quotes in mission_board.py (broke Python syntax)."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
f = ROOT / "src" / "mission_board.py"
src = f.read_text(encoding="utf-8")
orig = src

# Left and right curly double quote -> straight double quote
src = src.replace("“", '"')
src = src.replace("”", '"')
# Left and right curly single quote -> straight single quote (safety)
src = src.replace("‘", "'")
src = src.replace("’", "'")

changed = src != orig
if changed:
    f.write_text(src, encoding="utf-8")
    print("Fixed curly quotes -> straight quotes")
else:
    print("No changes")
