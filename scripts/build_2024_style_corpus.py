"""
build_2024_style_corpus.py -- mine a WotC-authored 2014 -> 2024 parallel corpus
from the Mimir catalog.

373 monsters appear under BOTH source='MM' (2014 Monster Manual) and source='XMM'
(2024 Monster Manual) in mimir.db. Where a creature has an ability of the same name
in both books, the pair is a genuine, published example of exactly the rewrite this
project keeps asking a model to perform:

    MM   Fire Breath. The dragon exhales fire in a 60-foot cone. Each creature in
         that area must make a DC 21 Dexterity saving throw, taking 63 (18d6) fire
         damage on a failed save, or half as much damage on a successful one.
    XMM  Fire Breath. Dexterity Saving Throw: DC 21, each creature in a 60-foot Cone.
         Failure: 63 (18d6) Fire damage. Success: Half damage.

This is grounding, not training. CLAUDE.md is explicit that rules content comes from
Mimir and never from model memory, so the fix for "the model does not know 2024" is
to SHOW it the real thing at call time, not to bake half-remembered rules into
weights. The corpus is written to MySQL (`training_docs`) so any pipeline can pull
the nearest real example for whatever it is about to rewrite.

Usage:
    python scripts/build_2024_style_corpus.py --report          # stats only
    python scripts/build_2024_style_corpus.py --write           # store in training_docs
    python scripts/build_2024_style_corpus.py --sample 5
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.db_api import raw_query, raw_execute  # noqa: E402

MIMIR_DB = Path(r"C:\Users\akodoreign\AppData\Roaming\com.mimir.app\data\mimir.db")

ABILITY = {"str": "Strength", "dex": "Dexterity", "con": "Constitution",
           "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}

BLOCK_KEYS = ("action", "trait", "reaction", "bonus", "legendary")


def render(text: str) -> str:
    """Expand 5etools markup into the plain prose a stat block actually prints."""
    s = text
    s = re.sub(r"\{@actSave (\w+)\}", lambda m: ABILITY[m.group(1)] + " Saving Throw:", s)
    s = re.sub(r"\{@dc (\d+)\}", r"DC \1", s)
    s = s.replace("{@actSaveFail}", "Failure:").replace("{@actSaveSuccess}", "Success:")
    s = re.sub(r"\{@actSaveSuccessOrFail\}", "Failure or Success:", s)
    s = re.sub(r"\{@atkr m,r\}", "Melee or Ranged Attack Roll:", s)
    s = re.sub(r"\{@atkr m\}", "Melee Attack Roll:", s)
    s = re.sub(r"\{@atkr r\}", "Ranged Attack Roll:", s)
    s = re.sub(r"\{@atk mw,rw\}", "Melee or Ranged Weapon Attack:", s)
    s = re.sub(r"\{@atk mw\}", "Melee Weapon Attack:", s)
    s = re.sub(r"\{@atk rw\}", "Ranged Weapon Attack:", s)
    s = re.sub(r"\{@atk ms\}", "Melee Spell Attack:", s)
    s = re.sub(r"\{@atk rs\}", "Ranged Spell Attack:", s)
    s = re.sub(r"\{@hit (\d+)\}", r"+\1", s)
    s = s.replace("{@h}", "Hit: ")
    s = re.sub(r"\{@recharge (\d+)\}", r"(Recharge \1-6)", s)
    s = re.sub(r"\{@recharge\}", "(Recharge 6)", s)
    # Any remaining tag: keep the display text, drop the source suffix.
    s = re.sub(r"\{@\w+ ([^|}]+)(\|[^}]*)?\}", r"\1", s)
    s = re.sub(r"\{@\w+\}", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()


def blocks(data: dict) -> dict[str, str]:
    """{ability name -> rendered text} across actions/traits/reactions/etc."""
    out: dict[str, str] = {}
    for key in BLOCK_KEYS:
        for entry in (data.get(key) or []):
            name = render(entry.get("name") or "").strip()
            if not name:
                continue
            body = " ".join(e for e in (entry.get("entries") or []) if isinstance(e, str))
            if body:
                out.setdefault(name, render(body))
    return out


def load_pairs() -> list[dict]:
    con = sqlite3.connect(f"file:{MIMIR_DB}?mode=ro", uri=True)
    cur = con.cursor()

    def by_source(src: str) -> dict[str, dict]:
        return {
            name: json.loads(data)
            for name, data in cur.execute(
                "SELECT name, data FROM monsters WHERE source=?", (src,)
            )
        }

    mm, xmm = by_source("MM"), by_source("XMM")
    pairs: list[dict] = []

    for name in sorted(set(mm) & set(xmm)):
        old_blocks, new_blocks = blocks(mm[name]), blocks(xmm[name])
        for ability, old_text in old_blocks.items():
            new_text = new_blocks.get(ability)
            if not new_text or new_text == old_text:
                continue
            # Only keep pairs that actually demonstrate a 2014 -> 2024 shift.
            teaches_save = ("saving throw" in old_text.lower()
                            and "Saving Throw:" in new_text)
            teaches_attack = ("Attack:" in old_text and "Attack Roll:" in new_text)
            if not (teaches_save or teaches_attack):
                continue

            # WotC did not merely reformat every ability -- plenty were redesigned
            # between editions (the Aboleth's Tentacle went from "diseased" at reach
            # 10 ft. to "Grappled" at reach 15 ft.). A redesigned pair would teach a
            # model that changing effects is allowed, which is the exact failure the
            # rewrite gate exists to stop. Keep only pairs whose numbers are
            # identical on both sides: those are pure reformatting.
            pure = Counter(re.findall(r"\d+", old_text)) == Counter(re.findall(r"\d+", new_text))

            pairs.append({
                "monster": name,
                "ability": ability,
                "old": f"{ability}. {old_text}",
                "new": f"{ability}. {new_text}",
                "teaches": "save" if teaches_save else "attack",
                "pure_reformat": pure,
            })

    con.close()
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--sample", type=int, default=0)
    args = ap.parse_args()

    if not MIMIR_DB.exists():
        print(f"Mimir catalog not found at {MIMIR_DB}")
        return 2

    pairs = load_pairs()
    saves = [p for p in pairs if p["teaches"] == "save"]
    attacks = [p for p in pairs if p["teaches"] == "attack"]
    monsters = {p["monster"] for p in pairs}

    pure = [p for p in pairs if p["pure_reformat"]]
    print(f"WotC 2014 -> 2024 pairs: {len(pairs)} "
          f"({len(saves)} save, {len(attacks)} attack) from {len(monsters)} monsters")
    print(f"  of those, PURE REFORMATS (numbers identical both sides): {len(pure)}"
          f"  [{len([p for p in pure if p['teaches'] == 'save'])} save, "
          f"{len([p for p in pure if p['teaches'] == 'attack'])} attack]")
    print(f"  redesigned between editions (NOT usable as style examples): "
          f"{len(pairs) - len(pure)}")

    for pair in pairs[:args.sample]:
        print(f"\n[{pair['monster']} / {pair['ability']}] teaches={pair['teaches']}")
        print(f"  2014: {pair['old'][:230]}")
        print(f"  2024: {pair['new'][:230]}")

    if args.write:
        raw_execute("DELETE FROM training_docs WHERE doc_type='style_2024_pair'")
        for pair in pairs:
            body = json.dumps(pair)
            raw_execute(
                "INSERT INTO training_docs (doc_type, filename, content, char_count) "
                "VALUES (%s, %s, %s, %s)",
                ("style_2024_pair",
                 f"{pair['monster']} -- {pair['ability']}",
                 body,
                 len(body)),
            )
        rows = raw_query(
            "SELECT COUNT(*) c FROM training_docs WHERE doc_type='style_2024_pair'"
        )
        print(f"\nstored in training_docs: {rows[0]['c']} pairs")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
