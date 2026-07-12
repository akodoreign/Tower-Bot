"""
wire_treasure_to_pipelines.py — Insert loot_card into all mission pipeline module renders.

For each pipeline, finds the first `return _page(` inside the render_*_module function
and inserts `body += _loot_card(mission)` (with lazy import) before it.

Run: python scripts/wire_treasure_to_pipelines.py
"""

import ast
import re
from pathlib import Path

PIPELINES_DIR = Path(__file__).resolve().parent.parent / "src" / "mission_builder"

# Each tuple: (file, function_name_pattern, indent_of_return)
# indent_of_return is how many spaces the `return _page(` line is indented.
TARGETS = [
    ("ambush_pipeline.py",             "render_ambush_module",         4),
    ("assassination_pipeline.py",      "render_assassination_module",  4),
    ("assault_pipeline.py",            "render_assault_module",        4),
    ("battle_pipeline.py",             "render_battle_module",         4),
    ("defense_pipeline.py",            "render_defense_module",        4),
    ("discovery_pipeline.py",          "render_module",                4),
    ("escort_pipeline.py",             "render_escort_module",         4),
    ("exploration_pipeline.py",        "render_module",                4),
    ("first_contact_pipeline.py",      "render_module",                4),
    ("gather_pipeline.py",             "render_gather_module",         4),
    ("heist_pipeline.py",              "render_heist_module",          4),
    ("infestation_pipeline.py",        "render_infestation_module",    4),
    ("infiltration_pipeline.py",       "render_infiltration_module",   4),
    ("investigation_pipeline.py",      "render_investigation_module",  4),
    ("negotiation_pipeline.py",        "render_negotiation_module",    4),
    ("puzzle_pipeline.py",             "render_puzzle_module",         4),
    ("recovery_pipeline.py",           "render_module",                4),
    ("rescue_pipeline.py",             "render_rescue_module",         4),
    ("sabotage_pipeline.py",           "render_sabotage_module",       4),
    ("strange_occurrences_pipeline.py","render_module",                4),
]

LOOT_IMPORT = "    from src.treasure import loot_card as _loot_card\n"
LOOT_INSERT = "    body += _loot_card(mission)\n"

MARKER = "# __LOOT_WIRED__"


def already_wired(text: str) -> bool:
    return MARKER in text or "_loot_card(mission)" in text


def find_function_start(lines: list[str], func_name: str) -> int:
    """Return line index (0-based) of `def func_name(`."""
    pattern = re.compile(rf"^def {re.escape(func_name)}\s*\(")
    for i, line in enumerate(lines):
        if pattern.match(line):
            return i
    return -1


def find_first_return_page(lines: list[str], func_start: int) -> int:
    """
    Starting from func_start, find the first line matching `    return _page(`.
    Stop at the next top-level function def.
    """
    for i in range(func_start + 1, len(lines)):
        line = lines[i]
        # Stop at next top-level def (not indented)
        if re.match(r"^(def |async def |class )", line) and i > func_start + 1:
            break
        if re.match(r"\s+return _page\(", line):
            return i
    return -1


def wire(filepath: Path, func_name: str) -> str:
    text = filepath.read_text(encoding="utf-8")
    if already_wired(text):
        return "already_wired"

    lines = text.splitlines(keepends=True)
    func_start = find_function_start(lines, func_name)
    if func_start == -1:
        return f"function_not_found: {func_name}"

    return_idx = find_first_return_page(lines, func_start)
    if return_idx == -1:
        return f"return_page_not_found in {func_name}"

    # Insert loot import + loot card before the return line
    lines.insert(return_idx, LOOT_INSERT)
    lines.insert(return_idx, LOOT_IMPORT)

    new_text = "".join(lines)

    # AST check before writing
    try:
        ast.parse(new_text)
    except SyntaxError as e:
        return f"syntax_error: {e}"

    filepath.write_bytes(new_text.encode("utf-8"))
    return "ok"


def main():
    results = []
    for filename, func_name, _ in TARGETS:
        path = PIPELINES_DIR / filename
        if not path.exists():
            results.append((filename, "file_not_found"))
            continue
        result = wire(path, func_name)
        results.append((filename, result))

    print("\n=== Treasure wiring results ===")
    ok = [r for r in results if r[1] == "ok"]
    already = [r for r in results if r[1] == "already_wired"]
    errors = [r for r in results if r[1] not in ("ok", "already_wired")]

    for f, status in results:
        icon = "OK" if status == "ok" else ("--" if status == "already_wired" else "FAIL")
        print(f"  [{icon}] {f}: {status}")

    print(f"\n{len(ok)} wired, {len(already)} already done, {len(errors)} errors")


if __name__ == "__main__":
    main()
