"""
build_tower_2024_model.py -- create the `tower-2024` Ollama model.

The base model does not know the D&D 2024 (5.5e) conventions; it was trained on a
world where 2014 phrasing dominates, so it drifts back to "Melee Weapon Attack: +6
to hit" and "must make a DC 15 Dexterity saving throw" whenever it is not watched.

This is model CUSTOMISATION, not fine-tuning: an Ollama Modelfile that pins a SYSTEM
prompt carrying the 2024 conventions plus real published examples mined from the
Mimir catalog by build_2024_style_corpus.py. It costs nothing to build, is instant
to rebuild, and can be deleted with `ollama rm tower-2024`.

Why not a LoRA fine-tune: CLAUDE.md is explicit that rules content comes from Mimir
and never from model memory. Baking rules into weights produces a model that recites
half-remembered statblocks confidently, which is strictly worse than one that reads
the catalog. What the model actually lacks is FORMAT knowledge, and a system prompt
plus retrieval teaches format without pretending to teach rules.

Usage:
    python scripts/build_tower_2024_model.py --show     # print the Modelfile
    python scripts/build_tower_2024_model.py --build    # ollama create tower-2024
    python scripts/build_tower_2024_model.py --test
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.db_api import raw_query  # noqa: E402

BASE = "qwen3-8b-slim:latest"
NAME = "tower-2024"

CONVENTIONS = """\
You are a Dungeon Master's assistant for a D&D 2024 (5.5e) campaign. The campaign
uses the 2024 Player's Handbook and the 2024 Monster Manual (XMM). It does NOT use
2014 phrasing. Write every rules-facing line the 2024 way.

ATTACKS
  2024: Melee Attack Roll: +6, reach 5 ft. Hit: 8 (1d8 + 4) Bludgeoning damage.
  2024: Ranged Attack Roll: +5, range 80/320 ft. Hit: 6 (1d6 + 3) Piercing damage.
  2024: Melee or Ranged Attack Roll: +7, reach 5 ft. or range 20/60 ft. Hit: ...
  NEVER write "Melee Weapon Attack:", "Ranged Spell Attack:", "+6 to hit", or
  ", one target." Those are 2014 forms and are wrong here.

SAVING THROWS
  2024: Dexterity Saving Throw: DC 15, each creature in a 20-foot Cone.
        Failure: 35 (10d6) Fire damage. Success: Half damage.
  The save leads. The DC comes next. Then WHO is affected -- always naming the
  targets ("each creature in a 30-foot Cone", "one creature within 30 feet"), never
  a bare area. Then Failure:, then Success:, then Failure or Success: if needed.
  NEVER write "must make a DC 15 Dexterity saving throw", "on a failed save", or
  "or half as much damage on a successful one".

VOCABULARY
  Damage types are capitalised: Bludgeoning, Piercing, Slashing, Fire, Cold, Acid,
  Poison, Necrotic, Radiant, Psychic, Thunder, Lightning, Force.
  Conditions are capitalised and phrased as "the target has the Frightened
  condition", never "is frightened". The 2024 conditions are Blinded, Charmed,
  Deafened, Frightened, Grappled, Incapacitated, Invisible, Paralyzed, Petrified,
  Poisoned, Prone, Restrained, Stunned, Unconscious, Exhaustion. Never invent one.
  Area shapes are capitalised: Cone, Line, Cube, Sphere, Emanation, Cylinder.
  Write "Hit Points", not "hit points" or "HP", in published stat block prose.
  Dice are spaced: "2d6 + 3", not "2d6+3".

DISCIPLINE
  You are a formatter and a writer, not a designer. When you are given existing
  rules text, never change a number, a DC, a die, a damage type, or a condition,
  and never add or remove an effect. If the source does not say what happens on a
  successful save, do not invent a Success: clause.
  Rules content for this campaign comes from the Mimir catalog, not from your
  memory. If you are asked for a statblock you have not been given, say what you
  need looked up rather than reciting one from memory."""


def worked_examples(limit: int = 6) -> str:
    """Real published 2014 -> 2024 rewrites mined from the Mimir catalog."""
    try:
        rows = raw_query(
            "SELECT content FROM training_docs WHERE doc_type='style_2024_pair'"
        ) or []
    except Exception:
        rows = []

    pure = []
    for row in rows:
        try:
            pair = json.loads(row["content"])
        except Exception:
            continue
        if pair.get("pure_reformat"):
            pure.append(pair)

    # Mix save and attack examples, shortest first so the prompt stays tight.
    saves = sorted([p for p in pure if p["teaches"] == "save"], key=lambda p: len(p["old"]))
    attacks = sorted([p for p in pure if p["teaches"] == "attack"], key=lambda p: len(p["old"]))
    picked = saves[:limit // 2] + attacks[:limit - limit // 2]
    if not picked:
        return ""

    lines = ["", "Worked examples of the same ability written both ways "
                 "(2014 wrong here, 2024 correct):"]
    for pair in picked:
        lines.append(f"  2014: {pair['old']}")
        lines.append(f"  2024: {pair['new']}")
    return "\n".join(lines)


def modelfile() -> str:
    system = CONVENTIONS + "\n" + worked_examples()
    return (
        f"FROM {BASE}\n\n"
        f"PARAMETER temperature 0.3\n"
        f"PARAMETER top_p 0.9\n"
        f"PARAMETER num_ctx 8192\n\n"
        f'SYSTEM """{system}"""\n'
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--name", default=NAME)
    args = ap.parse_args()

    if not (args.show or args.build or args.test):
        ap.error("pass --show, --build, or --test")

    text = modelfile()

    if args.show:
        print(text)

    if args.build:
        path = Path(__file__).resolve().parent.parent / "Modelfile.tower-2024"
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path} ({len(text)} chars)")
        result = subprocess.run(
            ["ollama", "create", args.name, "-f", str(path)],
            capture_output=True, text=True,
        )
        print(result.stdout.strip() or result.stderr.strip())
        if result.returncode != 0:
            return result.returncode
        print(f"\nbuilt: {args.name}")
        print(f"use it with  OLLAMA_MODEL={args.name}  or --model {args.name}")

    if args.test:
        probe = (
            "Write the attack line for a guard with a spear, +5 to hit equivalent, "
            "reach 5 feet, dealing 6 (1d6 + 3) piercing. Then write a DC 13 "
            "Dexterity save against a 15-foot cone dealing 10 (3d6) fire, half on a "
            "success. Output the two lines only."
        )
        result = subprocess.run(
            ["ollama", "run", args.name, probe],
            capture_output=True, text=True, timeout=300,
        )
        out = result.stdout.strip()
        print(out)
        bad = [m for m in ("Weapon Attack:", "to hit", "must make a DC",
                           "on a failed save", "saving throw,") if m in out]
        print("\n2014 leakage:", bad or "none")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
