"""Fix triple-quote sequences inside f-string prompts in mission_board.py."""
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
f = ROOT / "src" / "mission_board.py"
src = f.read_text(encoding="utf-8")
orig = src

# Inside the LLM prompt strings, visual separators like --- or "" were used.
# After encoding fixes, some became """ which breaks Python triple-quoted strings.
# Replace """ with -- (em dash style) everywhere EXCEPT true triple-quote delimiters.
# We do this line by line, skipping the actual opening/closing """ of f-strings.

lines = src.splitlines(keepends=True)
out = []
in_fstring = False

for i, line in enumerate(lines):
    stripped = line.strip()
    # Detect f-string / multiline string boundaries (starts with triple quote)
    if '"""' in line:
        # Count how many triple-quote sequences are on this line
        count = line.count('"""')
        if count >= 2:
            # Opening and closing on same line — no fixup needed
            out.append(line)
            continue
        # If the line is just an f-string delimiter (starts/ends the block), keep it
        if stripped.startswith('f"""') or stripped.startswith('"""') or stripped == '"""':
            out.append(line)
            in_fstring = not in_fstring
            continue
        if stripped.endswith('"""') and not stripped.startswith('"""'):
            out.append(line)
            in_fstring = False
            continue
        # Inside content: replace the visual """ separator with --
        fixed = line.replace('"""', '--')
        if fixed != line:
            print(f"  L{i+1}: fixed triple-quote -> --")
        out.append(fixed)
    else:
        out.append(line)

result = "".join(out)
if result != orig:
    f.write_text(result, encoding="utf-8")
    print("Written.")
else:
    print("No changes.")
