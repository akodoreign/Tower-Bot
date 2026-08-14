"""
rewrite_monster_saves_2024.py -- restructure 2014 save clauses in the `monsters`
table into 2024 (XMM) form, with byte-for-byte numeric validation.

The attack-line rewrite (scripts/rewrite_monsters_2024_phrasing.py) was pure regex
because it is pattern substitution. Save clauses are not: 2024 leads with the save
and moves the target clause after the DC, so the sentence has to be rebuilt.

    2014  Each enemy in a 30-foot cone must make a DC 16 CON save. On a failure,
          the target takes 40 (6d10) Force damage; on a success, half damage.
    2024  Constitution Saving Throw: DC 16, each creature in a 30-foot Cone.
          Failure: 40 (6d10) Force damage. Success: Half damage.

Target format verified against XMM rows in the Mimir catalog (Abominable Yeti,
Adult Black Dragon, Aboleth), not from model memory.

An LLM does the restructuring; it is NOT trusted with the rules content. Every
candidate must survive `validate()` before it can reach MySQL:

  * the multiset of every integer in the text must be identical (reorder allowed,
    because the DC legitimately moves ahead of the target clause -- but no number
    may be added, dropped, or altered)
  * dice expressions, DCs, damage types, conditions and the save ability must all
    match as multisets
  * the result must actually be 2024 form (has "Saving Throw:", no 2014 markers)
  * length must stay in a sane band, with no model chatter or markdown

A paragraph that fails validation twice is left exactly as it was and reported.
Nothing is ever written on a partial pass.

Usage:
    python scripts/rewrite_monster_saves_2024.py --dry-run --limit 5
    python scripts/rewrite_monster_saves_2024.py --apply
    python scripts/rewrite_monster_saves_2024.py --apply --model qwen3.6:27b
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.aclient import _peak_power_delay_seconds  # noqa: E402
from src.db_api import raw_query, raw_execute  # noqa: E402
from src.log import logger  # noqa: E402

# qwen3.6-27b is 17.4 GB against an 8 GB card, so it runs on CPU offload at roughly
# 150 s/paragraph vs 2 s for the 8B. Run the 8B first for the bulk, then re-run with
# --model qwen3.6-27b-slim:latest: the pass only picks up paragraphs that still match
# RE_SAVE_2014, so the big model naturally gets exactly the leftovers.
MODEL = "qwen3-8b-slim:latest"
BIG_MODEL = "qwen3.6-27b-slim:latest"

TEXT_FIELDS = (
    "actions", "traits", "reactions", "bonus_actions",
    "legendary_actions", "mythic_actions", "lair_actions",
)

ABILITIES = {
    "str": "Strength", "strength": "Strength",
    "dex": "Dexterity", "dexterity": "Dexterity",
    "con": "Constitution", "constitution": "Constitution",
    "int": "Intelligence", "intelligence": "Intelligence",
    "wis": "Wisdom", "wisdom": "Wisdom",
    "cha": "Charisma", "charisma": "Charisma",
}

DAMAGE_TYPES = (
    "bludgeoning", "piercing", "slashing", "fire", "cold", "acid", "poison",
    "necrotic", "radiant", "psychic", "thunder", "lightning", "force",
)

CONDITIONS = (
    "blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated",
    "invisible", "paralyzed", "petrified", "poisoned", "prone", "restrained",
    "stunned", "unconscious", "exhaustion",
)

# A paragraph needs rewriting if it carries a 2014-style save clause.
RE_SAVE_2014 = re.compile(
    r"DC\s*\d+\s*(?:STR|DEX|CON|INT|WIS|CHA|Strength|Dexterity|Constitution|"
    r"Intelligence|Wisdom|Charisma)\.?\s*(?:save|saving throw)",
    re.IGNORECASE,
)
RE_INT = re.compile(r"\d+")
RE_DICE = re.compile(r"\d+d\d+(?:\s*[+-]\s*\d+)?", re.IGNORECASE)
RE_DC = re.compile(r"DC\s*(\d+)", re.IGNORECASE)
RE_ABILITY = re.compile(
    r"\b(str|dex|con|int|wis|cha|strength|dexterity|constitution|"
    r"intelligence|wisdom|charisma)\b(?=[^a-z]*(?:save|saving throw|Saving Throw))",
    re.IGNORECASE,
)
RE_TYPE = re.compile(r"\b(" + "|".join(DAMAGE_TYPES) + r")\b", re.IGNORECASE)
RE_COND = re.compile(r"\b(" + "|".join(CONDITIONS) + r")\b", re.IGNORECASE)

# 2014 leftovers that prove the restructure did not happen.
RE_2014_MARKER = re.compile(
    r"must make a DC|must succeed on a DC|makes a DC|\bsave or\b|"
    r"on a failure|on a success",
    re.IGNORECASE,
)
# The clause after "Saving Throw: DC n," must name WHO is affected, not just the
# area -- "DC 14, a 15-foot Cone" is wrong, "DC 14, each creature in a 15-foot
# Cone" is right. XMM always leads with the target.
RE_TARGET_CLAUSE = re.compile(
    r"Saving Throw:\s*DC\s*\d+\s*,\s*(each|one|any|every|all|the)\b", re.IGNORECASE
)
# Numeric validation cannot see a flipped branch: the model has been observed
# turning "On success it drops to 1 HP" into "Failure: ... drops to 1 HP", which
# inverts the rule while every number stays identical. If the source had a
# success/failure branch, the rewrite must still have one.
RE_SRC_SUCCESS = re.compile(r"on (?:a )?success|successful save|if it succeeds", re.IGNORECASE)
RE_SRC_FAILURE = re.compile(r"on (?:a )?fail|failed save|if it fails|\bsave or\b", re.IGNORECASE)
# The inverse matters just as much. Observed inventions, all numerically clean:
#   "DC 16 Con save or max HP reduced."
#     -> "... Failure: max HP reduced. Success: max HP reduced by HALF that amount."
#   "DC 14 Con save or diseased as Bite."  ->  "... Success: None."
# The source had no success branch at all; the model made one up.
RE_HAS_SUCCESS_CLAUSE = re.compile(r"\bSuccess(?: or Failure)?:", re.IGNORECASE)
RE_HAS_FAILURE_CLAUSE = re.compile(r"\bFailure(?: or Success)?:", re.IGNORECASE)
# Conditions must be real 5e conditions -- the model invented "Skill Suppression".
# Capture only the Capitalised name(s) directly before "condition": a looser pattern
# is beaten by leftmost-match and grabs "target has the Stunned" out of
# "the target has the Stunned condition".
RE_COND_PHRASE = re.compile(
    r"\b(?:the|a|an)\s+((?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)?)\s+condition\b"
)
# Many paragraphs are an attack line FOLLOWED by a save rider. The attack line was
# already converted to 2024 by rewrite_monsters_2024_phrasing.py, and the model has
# been observed "helpfully" reverting it ("Melee Attack Roll: +6" -> "Melee Weapon
# Attack: +6 to hit"). It must come back byte-for-byte.
RE_ATTACK_HEAD = re.compile(r"(?:Melee or Ranged|Melee|Ranged)\s+Attack Roll:")
RE_ATTACK_2014 = re.compile(r"(?:Weapon|Spell)\s+Attack:|\bto hit\b", re.IGNORECASE)


def attack_span(text: str) -> str:
    """The already-2024 attack sentence that precedes a save rider, if any."""
    head = RE_ATTACK_HEAD.search(text)
    if not head:
        return ""
    save = RE_SAVE_2014.search(text, head.end())
    return text[head.start():(save.start() if save else len(text))].strip()

FALLBACK_FEW_SHOT = """\
2014: Each creature in a 30-foot cone must make a DC 18 CON save. On a failure, the target takes 45 (10d8) Cold damage; on a success, half damage.
2024: Constitution Saving Throw: DC 18, each creature in a 30-foot Cone. Failure: 45 (10d8) Cold damage. Success: Half damage.

2014: One creature the yeti can see within 30 ft. must make a DC 18 Con save or take 21 (6d6) Cold damage and be paralyzed until the start of the yeti's next turn.
2024: Constitution Saving Throw: DC 18, one creature the yeti can see within 30 feet. Failure: 21 (6d6) Cold damage, and the target has the Paralyzed condition until the start of the yeti's next turn.

2014: One creature within 30 ft. makes a DC 14 Wis save or is frightened for 1 minute (save ends each turn).
2024: Wisdom Saving Throw: DC 14, one creature within 30 feet. Failure: The target has the Frightened condition for 1 minute (save ends at the end of each of its turns)."""

SYSTEM = (
    "You reformat D&D monster stat block text from 2014 (5e) phrasing into 2024 "
    "(5.5e / Monster Manual 2024) phrasing. You are a FORMATTER, not a designer. "
    "You never invent, drop, or alter any rules value."
)

# ---------------------------------------------------------------------------
# Retrieval-grounded few-shot: show the model WotC's own rewrite, not ours
# ---------------------------------------------------------------------------
# The local model does not know the 2024 conventions, and CLAUDE.md forbids leaning
# on model memory for rules. scripts/build_2024_style_corpus.py mines the 373
# monsters that appear in BOTH MM (2014) and XMM (2024) and keeps the pairs whose
# numbers are identical on both sides -- genuine published examples of exactly this
# reformat. We hand the model the closest ones at call time.

_SHAPE_WORDS = ("cone", "line", "radius", "sphere", "emanation", "cube", "cylinder",
                "one creature", "each creature", "half", "recharge")


def _features(text: str) -> set:
    low = text.lower()
    feats = {w for w in _SHAPE_WORDS if w in low}
    feats |= {c for c in CONDITIONS if c in low}
    feats |= {d for d in DAMAGE_TYPES if d in low}
    return feats


_CORPUS: list[dict] | None = None


def _corpus() -> list[dict]:
    """Pure-reformat save pairs from training_docs, loaded once."""
    global _CORPUS
    if _CORPUS is None:
        _CORPUS = []
        try:
            rows = raw_query(
                "SELECT content FROM training_docs WHERE doc_type='style_2024_pair'"
            ) or []
            for row in rows:
                pair = json.loads(row["content"])
                if pair.get("pure_reformat") and pair.get("teaches") == "save":
                    _CORPUS.append(pair)
        except Exception as exc:
            logger.warning(f"[SAVE_2024] style corpus unavailable: {exc}")
    return _CORPUS


def few_shot_for(body: str, k: int = 3) -> str:
    """The k closest real WotC 2014->2024 pairs, as worked examples."""
    pairs = _corpus()
    if not pairs:
        return FALLBACK_FEW_SHOT

    want = _features(body)
    ranked = sorted(
        pairs,
        key=lambda p: len(want & _features(p["old"])) - 0.01 * len(p["old"]),
        reverse=True,
    )
    picked = ranked[:k]
    if not picked:
        return FALLBACK_FEW_SHOT

    return "\n\n".join(
        f"2014: {p['old']}\n2024: {p['new']}" for p in picked
    )


def _fit_ctx(prompt: str, reply_tokens: int) -> int:
    """Size num_ctx to prompt + planned reply. Unset num_ctx silently truncates.
    Local to this script by the no-shared-helpers rule (8192 floor, 32768 cap)."""
    needed = len(prompt) // 4 + reply_tokens + 768
    for cand in (8192, 12288, 16384, 24576, 32768):
        if cand >= needed:
            return cand
    return 32768


# ---------------------------------------------------------------------------
# Validation -- the LLM is never trusted with rules content
# ---------------------------------------------------------------------------

def _norm_dice(text: str) -> Counter:
    return Counter(re.sub(r"\s+", "", d).lower() for d in RE_DICE.findall(text))


def _abilities(text: str) -> Counter:
    return Counter(ABILITIES[a.lower()] for a in RE_ABILITY.findall(text))


def validate(before: str, after: str) -> tuple[bool, str]:
    """Return (ok, reason). Any failure means we keep the original untouched."""
    after = (after or "").strip()
    if not after:
        return False, "empty reply"

    if "```" in after or after.lower().startswith(("here", "sure", "certainly", "2024:")):
        return False, "model chatter or markdown fence"

    if "Saving Throw:" not in after:
        return False, "no 2024 'Saving Throw:' lead"

    leftover = RE_2014_MARKER.search(after)
    if leftover:
        return False, f"2014 marker survived: {leftover.group(0)!r}"

    still_2014 = RE_SAVE_2014.search(after)
    if still_2014:
        return False, f"2014 save construct survived: {still_2014.group(0)!r}"

    if not RE_TARGET_CLAUSE.search(after):
        return False, "no target clause after the DC (area given without 'each creature in')"

    src_success = bool(RE_SRC_SUCCESS.search(before))
    src_failure = bool(RE_SRC_FAILURE.search(before))
    out_success = bool(RE_HAS_SUCCESS_CLAUSE.search(after))
    out_failure = bool(RE_HAS_FAILURE_CLAUSE.search(after))

    if src_success and not out_success:
        return False, "source had a success branch, rewrite has no 'Success:' clause"
    if src_failure and not out_failure:
        return False, "source had a failure branch, rewrite has no 'Failure:' clause"
    if out_success and not src_success:
        return False, "invented a 'Success:' branch the source does not have"
    if out_failure and not src_failure:
        return False, "invented a 'Failure:' branch the source does not have"

    for m in RE_COND_PHRASE.finditer(after):
        name = m.group(1).strip().lower()
        if name not in CONDITIONS:
            return False, f"invented condition {m.group(1).strip()!r}"

    # An attack line that is already 2024 must survive the save rewrite untouched.
    span = attack_span(before)
    if span:
        reverted = RE_ATTACK_2014.search(after)
        if reverted:
            return False, f"reverted attack line to 2014: {reverted.group(0)!r}"
        if span not in after:
            return False, "attack line was modified"

    # Integers, damage types and conditions: an INVENTED or LOST value is a rules
    # change; a REPEATED one is formatting.
    #
    # These were multiset comparisons, which conflates the two. 2024 form requires
    # the area to be restated inside the save clause -- the source says "Each
    # rift: 10-ft. radius" and the rewrite must also say "each creature in a
    # 10-foot Radius" -- so a correct rewrite legitimately carries that 10 twice
    # and was rejected as "numbers changed (added ['10'])". Same for a damage type
    # or condition named once in the lead and again in the Failure clause.
    #
    # Set semantics still catch every real tampering: a changed DC introduces a
    # number the source never had AND loses one, an invented damage type appears
    # from nowhere, a dropped condition vanishes. And the load-bearing values have
    # their own STRICT multiset checks immediately below (dice, DC), so a number
    # that actually matters cannot be silently duplicated either.
    b_ints, a_ints = set(RE_INT.findall(before)), set(RE_INT.findall(after))
    if b_ints != a_ints:
        return False, (f"numbers changed (added {sorted(a_ints - b_ints)}, "
                       f"lost {sorted(b_ints - a_ints)})")

    if _norm_dice(before) != _norm_dice(after):
        return False, "dice expressions changed"

    if Counter(RE_DC.findall(before)) != Counter(RE_DC.findall(after)):
        return False, "DC values changed"

    b_types = {t.lower() for t in RE_TYPE.findall(before)}
    a_types = {t.lower() for t in RE_TYPE.findall(after)}
    if b_types != a_types:
        return False, (f"damage types changed ({sorted(a_types - b_types)} / "
                       f"{sorted(b_types - a_types)})")

    b_cond = {c.lower() for c in RE_COND.findall(before)}
    a_cond = {c.lower() for c in RE_COND.findall(after)}
    if b_cond != a_cond:
        return False, (f"conditions changed ({sorted(a_cond - b_cond)} / "
                       f"{sorted(b_cond - a_cond)})")

    if _abilities(before) != _abilities(after):
        return False, f"save ability changed ({_abilities(before)} -> {_abilities(after)})"

    # Length is only a chatter/truncation heuristic -- every rule-bearing check
    # (numbers, dice, DCs, damage types, conditions, save ability, 2014 markers,
    # branch preservation) has already run above.
    #
    # A pure ratio band is wrong for THIS corpus. These statblocks are written in
    # compressed shorthand ("DC 16 Wis save or frightened 1 minute." -- 8 words)
    # while 2024 form carries fixed scaffolding: "<Ability> Saving Throw: DC n,
    # <who>. Failure: ... Success: ...". That overhead is roughly constant, so on
    # a short source a faithful rewrite legitimately more than doubles it and a
    # 2.0x ceiling rejected correct output (3 of 23 first-pass failures). Allow
    # the scaffolding as a flat additive budget; keep the ratio for long text,
    # where genuine rambling actually shows up.
    words_b, words_a = len(before.split()), len(after.split())
    ceiling = max(2.0 * words_b, words_b + 16)
    if not (0.5 * words_b <= words_a <= ceiling):
        return False, f"length out of band ({words_b} -> {words_a} words)"

    if "\n" in after:
        return False, "multi-paragraph reply for a single paragraph"

    return True, "ok"


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

async def restructure(body: str, model: str, strict_retry: bool = False) -> str:
    from src.ollama_queue import call_ollama

    extra = ""
    if strict_retry:
        extra = (
            "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED. Copy every number, dice "
            "expression, DC, damage type and condition name EXACTLY as they appear "
            "in the input. Change only the sentence structure."
        )

    prompt = (
        f"Rewrite this D&D monster ability from 2014 phrasing into 2024 phrasing.\n\n"
        f"2024 save format is exactly:\n"
        f"<Ability> Saving Throw: DC <n>, <who is affected>. Failure: <effect>. "
        f"Success: <effect>.\n"
        f"Use 'Failure or Success:' for an effect that happens either way. Capitalise "
        f"condition names ('the target has the Frightened condition') and area shapes "
        f"('30-foot Cone'). Write distances as 'feet' in the target clause. Keep any "
        f"leading recharge/usage note such as '(Recharge 5-6)' or '(1/Day)' where it is.\n"
        f"The clause after the DC must name WHO is affected and always starts with "
        f"'each', 'one', 'the', 'any' or 'every' -- write 'DC 14, each creature in a "
        f"15-foot Cone', never 'DC 14, a 15-foot Cone'.\n\n"
        f"Worked examples (real published 2014 -> 2024 rewrites):\n{few_shot_for(body)}\n\n"
        f"HARD RULES:\n"
        f"- Do NOT change any number, dice expression, DC, damage type, or condition.\n"
        f"- Do NOT add or remove any effect.\n"
        f"- If the input opens with a SETUP sentence before the save (what happens, where "
        f"it happens, what appears), KEEP that sentence first, unchanged, then start the "
        f"'<Ability> Saving Throw:' line after it. 2024 does this too: 'While underwater, "
        f"the aboleth is surrounded by mucus. Constitution Saving Throw: DC 14, ...'. "
        f"Dropping the setup loses rules text and the result will be rejected.\n"
        f"- Write a 'Success:' clause ONLY if the input actually says what happens on a "
        f"success. If it does not, omit Success entirely -- never invent 'Success: None' "
        f"or a half-effect. The same goes for 'Failure:'.\n"
        f"- Only use the official conditions (Blinded, Charmed, Deafened, Frightened, "
        f"Grappled, Incapacitated, Invisible, Paralyzed, Petrified, Poisoned, Prone, "
        f"Restrained, Stunned, Unconscious, Exhaustion). Never invent a condition name; "
        f"if the effect is not one of those, describe it in plain words instead.\n"
        f"- If the input already contains an 'Attack Roll:' sentence, that part is "
        f"ALREADY 2024. Reproduce it character for character -- same wording, same "
        f"'ft.' abbreviations -- and rewrite ONLY the save clause that follows it. "
        f"Never turn 'Attack Roll:' back into 'Weapon Attack:' or add 'to hit'.\n"
        f"- Output ONE line of plain text: the rewritten ability only.\n"
        f"- No preamble, no explanation, no markdown, no quotes.{extra}\n\n"
        f"2014: {body}\n"
        f"2024:"
    )

    # A request-level system message REPLACES the Modelfile SYSTEM in /api/chat, so
    # sending ours to tower-2024 would throw away the 2024 conventions baked into it.
    messages = []
    if not model.startswith("tower-"):
        messages.append({"role": "system", "content": SYSTEM})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.15 if not strict_retry else 0.05,
            "num_predict": 700,
            "num_ctx": _fit_ctx(SYSTEM + prompt, 700),
        },
    }

    for attempt in range(1, 6):
        try:
            data = await call_ollama(payload, timeout=300.0, caller="save_rewrite", force=True)
            content = (data.get("message") or {}).get("content", "").strip()
            if content:
                content = re.sub(r"^2024:\s*", "", content).strip().strip('"')
                # 5etools markup bleeding out of the few-shot corpus. The WotC
                # source JSON tags areas as "{@variantrule Area of Effect|XPHB}";
                # the model reproduces the rendered leftover "[Area of Effect]",
                # which is corpus contamination, not rules text. Strip it rather
                # than let a bracketed editorial tag reach the statblock.
                content = re.sub(r"\s*\[Area of Effect\]", "", content)
                content = re.sub(r"\s{2,}", " ", content).strip()
                return content
        except Exception as exc:
            logger.warning(f"[SAVE_2024] Ollama error {attempt}/5: {exc}")
        if attempt < 5:
            await asyncio.sleep(min(10 * attempt, 45))
    return ""


# ---------------------------------------------------------------------------
# Paragraph plumbing
# ---------------------------------------------------------------------------

# The terminator has to be OPTIONAL at end of string. Requiring a trailing
# period made this a silent no-op whenever the model ended on
# "... Success: The target is unaffected" with no full stop -- which it usually
# does, because the clause it appends is the last thing it writes. That alone
# cost two full 27B passes: the trimmer looked wired up and recovered nothing.
RE_SUCCESS_SENTENCE = re.compile(
    r"\s*Success(?:\s+or\s+Failure)?:\s*[^.]*(?:\.(?:\s|$)|$)", re.IGNORECASE
)


def drop_invented_success(before: str, after: str) -> str:
    """Remove a Success: clause the source never had.

    Only fires when the SOURCE carries no success language at all -- a plain
    "DC 16 Wis save or Frightened 1 minute", whose correct 2024 form is a
    Failure: line and nothing else. If the source does describe what happens on
    a save, the clause is legitimate and is left exactly where it is.

    Deliberately does NOT touch numbers, dice, DCs or the Failure branch; it
    deletes one sentence and hands the result back to validate().
    """
    if not after or RE_SRC_SUCCESS.search(before or ""):
        return after
    if not RE_HAS_SUCCESS_CLAUSE.search(after):
        return after
    trimmed = RE_SUCCESS_SENTENCE.sub(" ", after).strip()
    trimmed = re.sub(r"\s{2,}", " ", trimmed)
    # Never hand back something that lost the Failure branch too.
    if not RE_HAS_FAILURE_CLAUSE.search(trimmed):
        return after
    return trimmed


def split_block(para: str) -> tuple[str, str]:
    """'Name. Body text' -> ('Name. ', 'Body text'). Mirrors how the renderer and
    _blocks_to_entries parse these fields, so the header must survive intact."""
    head, sep, rest = para.partition(". ")
    if sep and len(head) <= 60 and not RE_SAVE_2014.search(head):
        return head + ". ", rest
    return "", para


async def process_row(row: dict, model: str, dry_run: bool, report: list) -> dict[str, str]:
    updates: dict[str, str] = {}

    for field in TEXT_FIELDS:
        original = row.get(field) or ""
        if not RE_SAVE_2014.search(original):
            continue

        paras = original.split("\n\n")
        changed = False

        for i, para in enumerate(paras):
            if not RE_SAVE_2014.search(para):
                continue

            prefix, body = split_block(para)
            candidate = await restructure(body, model)
            ok, reason = validate(body, candidate)

            if not ok:
                logger.info(f"[SAVE_2024] retry {row['name']}/{field}: {reason}")
                candidate = await restructure(body, model, strict_retry=True)
                ok, reason = validate(body, candidate)

            if not ok:
                # By far the most common failure (10 of 23 on the first full
                # pass): the source is a plain "save or suffer X" with no
                # success behaviour, and the model appends a Success: clause
                # anyway because most 2024 saves have one. The restructure is
                # otherwise correct, so discarding it wastes a good rewrite.
                #
                # Deleting a clause the source never had is not the model
                # writing rules -- it restores fidelity to the source, and the
                # FULL validator runs again afterwards. If anything else is
                # wrong, it still fails.
                trimmed = drop_invented_success(body, candidate)
                if trimmed and trimmed != candidate:
                    ok2, reason2 = validate(body, trimmed)
                    if ok2:
                        logger.info(f"[SAVE_2024] recovered {row['name']}/{field}: "
                                    f"dropped an invented Success clause")
                        candidate, ok, reason = trimmed, ok2, reason2

            if not ok:
                report.append({
                    "id": row["id"], "name": row["name"], "field": field,
                    "reason": reason, "before": body, "rejected": candidate,
                })
                continue

            paras[i] = prefix + candidate
            changed = True
            if dry_run:
                print(f"\n{'-' * 74}\n#{row['id']} {row['name']} [{field}]")
                print(f"  BEFORE: {body}")
                print(f"  AFTER : {candidate}")

        if changed:
            updates[field] = "\n\n".join(paras)

    return updates


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="only process N monsters")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--report", default="", help="write rejected paragraphs to this JSON path")
    args = ap.parse_args()

    if not (args.apply or args.dry_run):
        ap.error("pass --dry-run or --apply")

    # Heavy GPU work must not land in the weekday 16:00-21:00 peak-rate window.
    delay = _peak_power_delay_seconds()
    if delay:
        print(f"REFUSING: weekday peak-rate window (89c/kWh). Ends in ~{delay // 60} min.")
        return 2

    cols = ", ".join(("id", "name", "cr", "source") + TEXT_FIELDS)
    rows = raw_query(f"SELECT {cols} FROM monsters ORDER BY id") or []
    todo = [r for r in rows
            if any(RE_SAVE_2014.search(r.get(f) or "") for f in TEXT_FIELDS)]
    if args.limit:
        todo = todo[:args.limit]

    print(f"{len(todo)} monsters carry 2014 save clauses; model={args.model}\n")

    report: list = []
    changed_rows = 0
    changed_fields = 0

    for n, row in enumerate(todo, 1):
        # Re-check every row: a long pass must not run INTO the peak-rate window,
        # only start outside it. Stopping early is safe -- rows already written are
        # committed, and a later run picks up whatever still matches RE_SAVE_2014.
        if _peak_power_delay_seconds():
            print(f"\nSTOPPING at {n - 1}/{len(todo)}: entered the weekday 16:00-21:00 "
                  f"peak-rate window. Re-run after 21:00 to finish the remainder.")
            break

        updates = await process_row(row, args.model, args.dry_run, report)
        if updates:
            changed_rows += 1
            changed_fields += len(updates)
            if args.apply:
                sets = ", ".join(f"{f}=%s" for f in updates)
                raw_execute(
                    f"UPDATE monsters SET {sets}, updated_at=NOW() WHERE id=%s",
                    tuple(updates.values()) + (row["id"],),
                )
        if n % 10 == 0 or n == len(todo):
            print(f"  ... {n}/{len(todo)} monsters | {changed_rows} rewritten "
                  f"| {len(report)} paragraphs left alone")

    print(f"\n{'applied' if args.apply else 'would apply'}: "
          f"{changed_rows} rows, {changed_fields} fields")
    print(f"left unchanged (failed validation twice): {len(report)} paragraphs")

    if report:
        by_reason = Counter(r["reason"].split("(")[0].strip() for r in report)
        for reason, count in by_reason.most_common():
            print(f"   {count:4}  {reason}")
    if args.report and report:
        Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
        print(f"rejected paragraphs -> {args.report}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
