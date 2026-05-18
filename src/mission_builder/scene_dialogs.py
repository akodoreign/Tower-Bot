"""
scene_dialogs.py — Generate player dialog options and visual clues for each mission scene.

Called from published_pipeline.py after the main module content is built.
Also used as a standalone patcher for already-generated modules.

Exported:
    generate_scene_dialogs(scene, ctx)  — async, returns {dialogs, visual_clues} dict
    build_dialog_html(scene_data)       — sync, returns HTML string to append to a scene
    inject_dialogs_into_module(module_html_path, scenes_data)  — patches existing HTML file
"""

from __future__ import annotations

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from typing import Optional, List, Dict

import httpx

from src.log import logger

OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")


# ---------------------------------------------------------------------------
# Ollama call
# ---------------------------------------------------------------------------

async def _ask(prompt: str, system: str = "", timeout: int = 120) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        from src.resource_cop import wait_for_ollama_turn

        decision = await wait_for_ollama_turn("scene_dialogs", track="primary")
        if not decision.run_now:
            logger.warning(f"[dialogs] Ollama deferred by resource cop: {decision.reason}")
            return ""

        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(OLLAMA_URL, json={
                "model":   OLLAMA_MODEL,
                "messages": messages,
                "stream":  False,
                "think":   False,
                "options": {"num_predict": 1800, "temperature": 0.75},
            })
            return r.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error(f"[dialogs] Ollama call failed: {e}")
        return ""


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

_SYSTEM = """You are a D&D 5e dungeon master assistant. You write tight, specific,
useful content for the DM to run at the table — not generic advice.
Write in present tense, active voice. Keep each entry to 1–2 sentences.
Output valid JSON only, no markdown fences, no commentary."""

def _build_prompt(scene: Dict, ctx: Dict) -> str:
    title        = ctx.get("title", "the mission")
    faction      = ctx.get("faction", "the faction")
    scene_name   = scene.get("name", "this scene")
    read_aloud   = scene.get("read_aloud", "")
    npcs         = scene.get("npcs", "")
    checks       = scene.get("checks", "")
    what_happens = scene.get("what_happens", "")
    transition   = scene.get("transition", "")
    secret       = scene.get("secret", "")

    return f"""Mission: "{title}" (faction: {faction})
Scene: {scene_name}

Read-aloud: {read_aloud}
NPCs: {npcs}
Checks: {checks}
What happens: {what_happens}
Transition: {transition}
DM secret: {secret}

Generate exactly this JSON structure (no markdown, no extra text):
{{
  "dialogs": [
    {{"trigger": "If players ask/do X", "response": "NPC or world does Y (include DC or mechanic if relevant)"}},
    ... at least 12 entries covering: questioning NPCs, pressing for secrets, intimidation, bribery,
        trying to leave early, casting detect thoughts/charm/zone of truth, searching the area,
        asking about the faction, asking about the mission backstory, failed checks, unusual creative actions
  ],
  "visual_clues": [
    {{"element": "specific thing they can see/smell/hear/touch", "detail": "what it reveals and why it matters"}},
    ... exactly 5 entries — make them concrete and actionable at the table
  ],
  "leaving_the_scene": {{
    "mood": "One sentence: how the party should feel emotionally as they leave — the tone the DM should project. e.g. 'The party should feel watched, not threatened — like someone closed a door just before they turned around.'",
    "direction": "One concrete sentence: exactly where they go next and what pulls them there.",
    "departure_options": [
      "A specific atmospheric way they might leave — action + flavour. e.g. 'They slip out through the canal-side exit just as a second patrol rounds the corner.'",
      "Another departure option with a different feel — cautious, bold, or fragmented.",
      "A third option for parties that linger or want one last thing before going."
    ],
    "lingers": "One vivid sensory detail they can't shake — smell, sound, image, or feeling that follows them into the next scene."
  }}
}}"""


# ---------------------------------------------------------------------------
# HTML renderer for dialog + clue blocks
# ---------------------------------------------------------------------------

def build_dialog_html(data: Dict) -> str:
    """Render dialog table + visual clues block as HTML. Safe for direct injection."""
    dialogs      = data.get("dialogs", [])
    visual_clues = data.get("visual_clues", [])

    parts = []

    if dialogs:
        rows = "\n".join(
            f'<tr>'
            f'<td class="dialog-trigger">{_esc(d.get("trigger",""))}</td>'
            f'<td class="dialog-response">{_esc(d.get("response",""))}</td>'
            f'</tr>'
            for d in dialogs if d.get("trigger") and d.get("response")
        )
        parts.append(
            f'<div class="dialog-block">'
            f'<span class="dialog-label">💬 Possible Player Dialogs</span>'
            f'<table class="dialog-table">'
            f'<thead><tr><th>If players ask / do…</th><th>NPC or world responds…</th></tr></thead>'
            f'<tbody>{rows}</tbody>'
            f'</table>'
            f'</div>'
        )

    if visual_clues:
        items = "\n".join(
            f'<li><strong>{_esc(c.get("element",""))}</strong> — {_esc(c.get("detail",""))}</li>'
            for c in visual_clues if c.get("element") and c.get("detail")
        )
        parts.append(
            f'<div class="clue-block">'
            f'<span class="clue-label">🔍 Visual Clues &amp; Sensory Details</span>'
            f'<ul>{items}</ul>'
            f'</div>'
        )

    leaving = data.get("leaving_the_scene") or {}
    if leaving:
        parts.append(build_leaving_html(leaving))

    return "\n".join(parts)


def build_leaving_html(leaving: Dict) -> str:
    """Render the Leaving the Scene block as HTML."""
    mood     = leaving.get("mood", "")
    direction = leaving.get("direction", "")
    # support both old key and new key
    travels  = leaving.get("travel_options") or leaving.get("departure_options", [])
    lingers  = leaving.get("lingers", "")

    travel_items = "\n".join(
        f'<li>{_esc(d)}</li>' for d in travels if d
    )

    return (
        f'<div class="leaving-block">'
        f'<span class="leaving-label">🚪 Leaving the Scene</span>'
        f'<div class="leaving-grid">'
        + (f'<div class="leaving-row"><span class="leaving-key">Mood</span><span class="leaving-val">{_esc(mood)}</span></div>' if mood else "")
        + (f'<div class="leaving-row"><span class="leaving-key">Where next</span><span class="leaving-val">{_esc(direction)}</span></div>' if direction else "")
        + (f'<div class="leaving-row"><span class="leaving-key">It lingers</span><span class="leaving-val leaving-lingers">{_esc(lingers)}</span></div>' if lingers else "")
        + f'</div>'
        + (f'<div class="leaving-departures-label">How to get there</div><ul class="leaving-departures">{travel_items}</ul>' if travel_items else "")
        + f'</div>'
    )


def _esc(t: str) -> str:
    import html
    return html.escape(str(t or ""))


def _clean_json(raw: str) -> str:
    """Normalize model output before JSON parsing."""
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.replace("’", "'").replace("‘", "'")
    raw = raw.replace("“", '"').replace("”", '"')
    raw = raw.replace("—", "--").replace("–", "-")
    raw = raw.replace("…", "...").replace(" ", " ")
    raw = raw.replace("\'", "'")  # remove invalid JSON escape before apostrophes
    # Literal newlines inside JSON string values break json.loads
    cleaned = []
    in_string = False
    escape_next = False
    for ch in raw:
        if escape_next:
            cleaned.append(ch)
            escape_next = False
        elif ch == "\\" and in_string:
            cleaned.append(ch)
            escape_next = True
        elif ch == '"':
            in_string = not in_string
            cleaned.append(ch)
        elif in_string and ord(ch) in (10, 13):
            cleaned.append(" ")
        else:
            cleaned.append(ch)
    return "".join(cleaned).strip()


def _parse_json_safe(raw: str) -> dict:
    """Parse JSON from model output, tolerating common formatting issues."""
    raw = _clean_json(raw)
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return _regex_extract(raw)


def _regex_extract(raw: str) -> dict:
    """Last-resort field extractor when json.loads fails on any variation."""
    def _str(key):
        m = re.search(r'"' + key + r'"\s*:\s*"((?:[^"\\]|\\.)*)"', raw, re.DOTALL)
        if not m:
            return ""
        return m.group(1).replace("\\'", "'").replace('\\"', '"')

    def _lst(key):
        m = re.search(r'"' + key + r'"\s*:\s*\[(.*?)\]', raw, re.DOTALL)
        if not m:
            return []
        return [x.replace("\\'", "'") for x in re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))]

    out = {}
    for f in ("mood", "direction", "lingers"):
        v = _str(f)
        if v:
            out[f] = v
    deps = _lst("travel_options") or _lst("departure_options")
    if deps:
        out["travel_options"] = deps
    dialogs = re.findall(
        r'\{\s*"trigger"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"response"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
        raw
    )
    if dialogs:
        out["dialogs"] = [{"trigger": t, "response": r} for t, r in dialogs]
    clues = re.findall(
        r'\{\s*"element"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"detail"\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}',
        raw
    )
    if clues:
        out["visual_clues"] = [{"element": e, "detail": d} for e, d in clues]
    return out


# ---------------------------------------------------------------------------
# Scene extractor — pull structured data from rendered module HTML
# ---------------------------------------------------------------------------

def _strip_tags(html_str: str) -> str:
    return re.sub(r"<[^>]+>", " ", html_str).replace("&amp;", "&").replace("&#x27;", "'").replace("&quot;", '"').strip()


def extract_scenes_from_html(module_html: str) -> List[Dict]:
    """
    Parse module HTML and return a list of scene dicts with their text content
    and the anchor point where dialog HTML should be inserted (just before <hr> or end of scene).
    """
    scenes = []

    # Split on <h3>Scene N: or <h3>Scene N (anything)
    # Also match lead headings
    scene_pat = re.compile(
        r'(<h3>(?:Scene|Lead)\s*\d+[^<]*</h3>)',
        re.IGNORECASE,
    )
    parts = scene_pat.split(module_html)

    for i, part in enumerate(parts):
        if not scene_pat.match(part):
            continue
        heading_html = part
        # Body is the next chunk
        body_html = parts[i + 1] if i + 1 < len(parts) else ""
        scene_name = _strip_tags(heading_html)

        # Stop pattern: next heading OR hr OR any injected block (dialog/clue/leaving)
        _STOP = r'(?=<h3>|<hr>|<div class="(?:dialog|clue|leaving)-block")'

        def _section(label: str) -> str:
            m = re.search(
                rf'<h3>{re.escape(label)}</h3>(.*?)' + _STOP + r'|$',
                body_html, re.DOTALL | re.IGNORECASE
            )
            return _strip_tags(m.group(1)) if m and m.group(1) else ""

        def _read_aloud() -> str:
            m = re.search(r'class="read-aloud"[^>]*>(.*?)</div>', body_html, re.DOTALL)
            return _strip_tags(m.group(1)) if m else ""

        def _gm_secret() -> str:
            m = re.search(r'class="gm-note"[^>]*>(.*?)</div>', body_html, re.DOTALL)
            return _strip_tags(m.group(1)) if m else ""

        scenes.append({
            "name":         scene_name,
            "read_aloud":   _read_aloud(),
            "npcs":         _section("NPCs Present"),
            "checks":       _section("Checks and Branches"),
            "what_happens": _section("What Happens"),
            "transition":   _section("Transition"),
            "secret":       _gm_secret(),
            # Where to insert: just before trailing <hr> or stat-block
            "_heading_html": heading_html,
            "_body_html":    body_html,
        })

    return scenes


# ---------------------------------------------------------------------------
# HTML patcher — injects dialog blocks into an existing module.html
# ---------------------------------------------------------------------------

def inject_dialogs_into_html(module_html: str, scene_dialogs: List[Dict]) -> str:
    """
    For each scene in scene_dialogs, insert the dialog HTML just before the
    trailing <hr> separator (or before a stat-block if that comes first).
    scene_dialogs: list of {"name": ..., "html": <rendered dialog html>}
    """
    result = module_html

    for sd in scene_dialogs:
        heading_text = sd.get("name", "").strip()
        dialog_html  = sd.get("html", "")
        if not dialog_html:
            continue

        # Find the h3 heading for this scene in the current result
        heading_pat = re.compile(
            r'(<h3>' + re.escape(heading_text) + r'</h3>)',
            re.IGNORECASE,
        )
        m = heading_pat.search(result)
        if not m:
            logger.warning(f"[dialogs] Could not find scene heading: {heading_text!r}")
            continue

        # Find the scene body: everything from after the heading to the next <h3>Scene or <h2> or end
        body_start = m.end()
        next_scene = re.search(r'<h[23][^>]*>(?:Scene|Lead|Resolution|Act)\s*\d*', result[body_start:], re.IGNORECASE)
        if next_scene:
            body_end = body_start + next_scene.start()
        else:
            body_end = len(result)

        scene_chunk = result[body_start:body_end]

        # Insert before the last <hr> in this chunk, or before a trailing stat-block, or at end
        hr_pos = scene_chunk.rfind("<hr>")
        sb_pos = scene_chunk.rfind('<div class="stat-block">')

        # Find the latest sensible insertion point (before hr, before stat-block)
        candidates = []
        if hr_pos != -1:
            candidates.append(hr_pos)
        if sb_pos != -1:
            candidates.append(sb_pos)

        if candidates:
            insert_at = min(candidates)  # whichever comes first in the scene
        else:
            insert_at = len(scene_chunk)

        new_scene_chunk = scene_chunk[:insert_at] + dialog_html + "\n" + scene_chunk[insert_at:]
        result = result[:body_start] + new_scene_chunk + result[body_end:]

    return result


# ---------------------------------------------------------------------------
# Public: generate dialogs for all scenes in a module
# ---------------------------------------------------------------------------

async def generate_all_scene_dialogs(
    module_html: str,
    ctx: Dict,
    pause_secs: float = 3.0,
) -> List[Dict]:
    """
    Extract scenes from module HTML, call Ollama for each, return list of
    {"name": scene_name, "html": rendered_dialog_html} dicts.
    """
    scenes = extract_scenes_from_html(module_html)
    if not scenes:
        logger.warning("[dialogs] No scenes found in module HTML")
        return []

    results = []
    for scene in scenes:
        logger.info(f"[dialogs] Generating dialog for: {scene['name']}")
        raw  = await _ask(_build_prompt(scene, ctx), system=_SYSTEM)
        data = _parse_json_safe(raw)
        if not data:
            logger.warning(f"[dialogs] JSON parse failed for {scene['name']}")
        html = build_dialog_html(data) if data else ""
        results.append({"name": scene["name"], "html": html})
        await asyncio.sleep(pause_secs)

    return results


async def patch_module_file(module_html_path: Path, ctx: Dict) -> bool:
    """
    Generate and inject dialog + visual clues + leaving sections into an existing module.html.
    Returns True on success.
    """
    try:
        original = module_html_path.read_text(encoding="utf-8")
        scene_dialogs = await generate_all_scene_dialogs(original, ctx)
        if not any(sd.get("html") for sd in scene_dialogs):
            return False
        patched = inject_dialogs_into_html(original, scene_dialogs)
        module_html_path.write_text(patched, encoding="utf-8")
        logger.info(f"[dialogs] Patched {module_html_path.name} with {len(scene_dialogs)} scene dialog blocks")
        return True
    except Exception as e:
        logger.error(f"[dialogs] patch_module_file failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Leaving-only patcher — for modules already patched with dialog+clues
# ---------------------------------------------------------------------------

_LEAVING_SYSTEM = """You are a D&D 5e dungeon master assistant writing vivid, table-ready content.
Precise rules you must follow:
- Output valid JSON only. No markdown fences, no commentary, no extra keys.
- mood: one punchy sentence, specific to THIS scene's action — avoid "the air hums" or generic dread.
- direction: poetically rephrase where they are going — do NOT copy the transition text word for word. Name the place naturally.
- travel_options: exactly 3 items. Each MUST start with one emoji from this set based on the approach:
    ⚡ fast but risky/exposed  |  🐾 slow and hidden  |  🤝 via a contact or faction resource  |  🎭 through deception or misdirection  |  🗺️ split-party or prepared approach
  After the emoji, write an imperative sentence ("Head through...", "Slip past...", "Find the...") — NOT "They do X".
  Max 35 words per option. Name a real street, landmark, or city feature from the Undercity.
  Each option must have a different emoji.
- lingers: purely sensory — a smell, sound, or physical sensation the party carries with them. No thoughts, memories, or dialogue echoes."""

def _leaving_prompt(scene: Dict, ctx: Dict) -> str:
    transition = scene.get('transition', '').strip()
    return f"""Mission: "{ctx.get('title','')}" (faction: {ctx.get('faction','')})
Scene: {scene.get('name','')}

Read-aloud: {scene.get('read_aloud','')}
NPCs present: {scene.get('npcs','')}

TRANSITION — the canonical next destination. Your leaving section must flow FROM this:
"{transition}"

Do NOT copy this sentence into "direction". Paraphrase it evocatively.

Output exactly this JSON:
{{
  "mood": "One sharp sentence capturing how the party feels as they leave — tied to what just happened, not generic atmosphere.",
  "direction": "Poetic one-sentence restatement of the destination — name the place, object, or person pulling them forward. Do not copy the transition verbatim.",
  "travel_options": [
    "EMOJI Imperative sentence naming a real Undercity street/landmark. One complication. Max 35 words.",
    "EMOJI Different approach — different emoji, different risk profile. Max 35 words.",
    "EMOJI Third option — split-party, contact, or unexpected angle. Max 35 words."
  ],
  "lingers": "One physical sensory detail — smell, sound, or sensation only. No thoughts or words."
}}"""


def _extract_place_names(text: str) -> List[str]:
    """
    Extract proper-noun place names from text.
    Strategy (in priority order):
      1. Consecutive capitalised words of 2+ words (e.g. "Shattered Vein", "Night Pits")
      2. Single capitalised words that look like names (not sentence starters)
      3. Quoted phrases
    Returns lowercased candidates.
    """
    names = []

    # 1. Multi-word capitalised sequences — strongest signal for place names
    for phrase in re.findall(r'\b(?:[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)+\b', text):
        names.append(phrase.lower())

    # 2. Single capitalised words mid-sentence (not at sentence start)
    # Find them by looking for caps words NOT preceded by ". " or start-of-string
    for m in re.finditer(r'(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{3,})\b', text):
        word = m.group(1).lower()
        # Filter out common non-place words
        if word not in {
            "the", "this", "that", "they", "them", "their", "with", "from",
            "have", "been", "were", "what", "when", "where", "which", "into",
            "back", "route", "through", "carries", "carried", "answer", "clues",
            "someone", "party", "scene", "transition", "agrees", "agree",
        }:
            names.append(word)

    # 3. Quoted phrases
    for phrase in re.findall(r'"([^"]{3,})"', text):
        names.append(phrase.lower().strip(".,;: "))

    return names


def _direction_matches_transition(direction: str, transition: str) -> bool:
    """
    Check whether the generated 'direction' text references the same
    destination as the scene's Transition text.

    Focuses on proper-noun place names — consecutive capitalised words
    like 'Shattered Vein' or 'Night Pits' — rather than generic words.
    Returns True when there's nothing meaningful to check against.
    """
    if not transition or not direction:
        return True

    place_names = _extract_place_names(transition)
    if not place_names:
        return True  # no identifiable place in transition — can't validate

    direction_lower = direction.lower()

    # Multi-word place names must match as full phrases
    multi = [n for n in place_names if ' ' in n]
    single = [n for n in place_names if ' ' not in n]

    # Any multi-word match is a strong pass
    if any(n in direction_lower for n in multi):
        return True

    # For single words, require at least 2 to appear (reduces false positives)
    single_hits = sum(1 for n in single if n in direction_lower)
    if single_hits >= 2:
        return True

    # One single-word hit is borderline — pass only if it's a clear place-name word
    clear_place_words = {"vein", "pits", "row", "vault", "spire", "forum",
                         "sanctum", "warrens", "docks", "quarter", "market",
                         "bazaar", "cistern", "tower", "arena", "alley"}
    if single_hits == 1 and any(
        n in direction_lower for n in single if n in clear_place_words
    ):
        return True

    logger.debug(
        f"[dialogs] Direction mismatch — transition places {place_names}, "
        f"direction: {direction[:80]!r}"
    )
    return False


def _correction_prompt(scene: Dict, ctx: Dict, bad_direction: str) -> str:
    """Prompt for a retry when the direction doesn't match the transition."""
    transition = scene.get('transition', '').strip()
    return f"""Your previous "direction" was wrong:
"{bad_direction}"

The Transition clearly states the next destination:
"{transition}"

Rewrite the full leaving block. "direction" must name the place from the Transition — paraphrased, not copied.
Follow all formatting rules: mood is scene-specific, travel_options start with emoji then imperative verb, lingers is sensory only.

Output this JSON only:
{{
  "mood": "Sharp one sentence — what this scene's outcome FEELS like as the party leaves.",
  "direction": "Evocative one sentence naming the Transition destination without copying it verbatim.",
  "travel_options": [
    "⚡ or 🐾 or 🤝 or 🎭 or 🗺️ — then imperative sentence, Undercity landmark, one complication. Max 35 words.",
    "Different emoji — different risk profile. Max 35 words.",
    "Third emoji option. Max 35 words."
  ],
  "lingers": "Smell, sound, or physical sensation only. No words or thoughts."
}}"""


async def generate_leaving_sections(module_html: str, ctx: Dict, pause_secs: float = 3.0) -> List[Dict]:
    """
    Generate 'leaving the scene' blocks for each scene.
    Validates that the generated direction matches the scene's Transition text;
    retries once with a corrective prompt if it doesn't.
    Returns list of {"name": scene_name, "leaving_html": html_string}.
    """
    scenes = extract_scenes_from_html(module_html)
    if not scenes:
        return []

    results = []
    for scene in scenes:
        logger.info(f"[dialogs] Generating leaving section for: {scene['name']}")
        transition = scene.get('transition', '').strip()

        raw  = await _ask(_leaving_prompt(scene, ctx), system=_LEAVING_SYSTEM, timeout=90)
        data = _parse_json_safe(raw)
        if not data:
            logger.warning(f"[dialogs] Leaving JSON parse failed for {scene['name']}")

        # Validate direction against transition text; retry once if mismatched
        if data and transition:
            direction = data.get('direction', '')
            if not _direction_matches_transition(direction, transition):
                logger.warning(
                    f"[dialogs] Direction mismatch in {scene['name']!r} — "
                    f"got {direction[:60]!r}, expected reference to: {transition[:60]!r}. Retrying."
                )
                await asyncio.sleep(2)
                raw2  = await _ask(_correction_prompt(scene, ctx, direction), system=_LEAVING_SYSTEM, timeout=90)
                data2 = _parse_json_safe(raw2)
                if data2 and _direction_matches_transition(data2.get('direction', ''), transition):
                    data = data2
                    logger.info(f"[dialogs] Retry corrected direction for {scene['name']!r}")
                else:
                    logger.warning(f"[dialogs] Retry still mismatched for {scene['name']!r} — keeping original")

        leaving_html = build_leaving_html(data) if data else ""
        results.append({"name": scene["name"], "leaving_html": leaving_html})
        await asyncio.sleep(pause_secs)

    return results


def _strip_duplicate_leaving(module_html: str) -> str:
    """Remove all but the first leaving-block in each scene (idempotency guard)."""
    result = module_html
    # Deduplicate globally: keep only the first occurrence of each leaving-block
    # by removing consecutive duplicates
    while result.count('<div class="leaving-block">') > result.count('<h3>Scene') + result.count('<h3>Lead'):
        idx = result.find('<div class="leaving-block">')
        idx2 = result.find('<div class="leaving-block">', idx + 1)
        if idx2 == -1:
            break
        # Count nested divs to find the real closing tag; start depth=1 (already inside the opening tag)
        depth = 1
        pos = idx2 + len('<div class="leaving-block">')
        while pos < len(result):
            if result[pos:pos+5] == '<div ':
                depth += 1
            elif result[pos:pos+6] == '</div>':
                depth -= 1
                if depth == 0:
                    result = result[:idx2] + result[pos+6:]
                    break
            pos += 1
    return result


def inject_leaving_into_html(module_html: str, leaving_sections: List[Dict]) -> str:
    """
    Insert each leaving block immediately after the last .clue-block in the scene.
    Falls back to inserting before <hr> or stat-block if no clue-block found.
    """
    result = module_html

    for ls in leaving_sections:
        heading_text = ls.get("name", "").strip()
        leaving_html = ls.get("leaving_html", "")
        if not leaving_html:
            continue

        heading_pat = re.compile(
            r'(<h3>' + re.escape(heading_text) + r'</h3>)',
            re.IGNORECASE,
        )
        m = heading_pat.search(result)
        if not m:
            logger.warning(f"[dialogs] Leaving: could not find heading: {heading_text!r}")
            continue

        body_start = m.end()
        next_scene = re.search(
            r'<h[23][^>]*>(?:Scene|Lead|Resolution|Act)\s*\d*',
            result[body_start:], re.IGNORECASE
        )
        body_end = body_start + next_scene.start() if next_scene else len(result)
        scene_chunk = result[body_start:body_end]

        # Skip if this scene already has a leaving-block (idempotent)
        if 'leaving-block' in scene_chunk:
            continue

        # Prefer: after the last clue-block closing tag
        clue_end = scene_chunk.rfind('</div>', scene_chunk.rfind('clue-block'))
        if clue_end != -1:
            insert_at = clue_end + len('</div>')
        else:
            # Fallback: before hr or stat-block
            hr_pos = scene_chunk.rfind("<hr>")
            sb_pos = scene_chunk.rfind('<div class="stat-block">')
            candidates = [p for p in [hr_pos, sb_pos] if p != -1]
            insert_at = min(candidates) if candidates else len(scene_chunk)

        new_chunk = scene_chunk[:insert_at] + "\n" + leaving_html + "\n" + scene_chunk[insert_at:]
        result = result[:body_start] + new_chunk + result[body_end:]

    return result


async def patch_leaving_sections(module_html_path: Path, ctx: Dict) -> bool:
    """Add only leaving-the-scene blocks to an already dialog-patched module.html."""
    try:
        original = module_html_path.read_text(encoding="utf-8")
        leaving  = await generate_leaving_sections(original, ctx)
        if not leaving:
            return False
        patched = inject_leaving_into_html(original, leaving)
        module_html_path.write_text(patched, encoding="utf-8")
        logger.info(f"[dialogs] Leaving sections added to {module_html_path.name} ({len(leaving)} scenes)")
        return True
    except Exception as e:
        logger.error(f"[dialogs] patch_leaving_sections failed: {e}")
        return False
