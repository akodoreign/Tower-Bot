"""Restore incorrectly-replaced triple-quote delimiters in mission_board.py."""
from pathlib import Path

f = Path(__file__).resolve().parent.parent / "src" / "mission_board.py"
src = f.read_text(encoding="utf-8")
orig = src

FIXES = [
    # _LORE string opening delimiter
    ('_LORE = --\\',                        '_LORE = """\\'),

    # f-string openings — _LORE interpolation
    ('prompt = f--{_LORE}',                 'prompt = f"""{_LORE}'),
    ('return f--{_LORE}',                   'return f"""{_LORE}'),

    # f-string openings — inline prompt strings
    ('prompt = f--You are',                 'prompt = f"""You are'),
    ('return f--You are',                   'return f"""You are'),
    ('fail_prompt = f--You are',            'fail_prompt = f"""You are'),

    # Comment line: restore """ example in the comment text
    ('"HOOK --, etc.)',                      '"HOOK """, etc.)'),

    # split(--", 1) → split('"', 1)  — both occurrences share same pattern
    ('.split(--", 1)[0].split("-", 1)',     '.split(\'"\', 1)[0].split("-", 1)'),

    # Broken regex line — replace whole broken expression with working version
    (
        'for match in re.finditer(r"â\\s*([^""\\n]+)\\s*--, body):',
        "for match in re.finditer(r'\\u2022\\s*([^\"\\n]+)\\s*', body):",
    ),
]

changed = 0
for old, new in FIXES:
    n = src.count(old)
    if n:
        src = src.replace(old, new)
        changed += n
        print(f"  Fixed {n}x: {repr(old)[:70]}")
    else:
        print(f"  NOT FOUND: {repr(old)[:70]}")

if src != orig:
    f.write_text(src, encoding="utf-8")
    print(f"\nWritten. {changed} replacements.")
else:
    print("No changes.")
