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

def _fit_ctx(prompt: str, reply_tokens: int) -> int:
    """Size the Ollama context window to the prompt + planned reply. With no
    num_ctx set, Ollama uses a small default and silently truncates either the
    oversized prompt or the long reply (yielding empty/unparseable output).
    Only raises; capped at 32k. Local to this module by the no-shared-helpers
    rule."""
    needed = len(prompt) // 4 + reply_tokens + 768
    for cand in (8192, 12288, 16384, 24576, 32768):
        if cand >= needed:
            return cand
    return 32768


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
                "options": {"num_predict": 1800, "temperature": 0.75, "num_ctx": _fit_ctx(system + prompt, 1800)},
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


# ---------------------------------------------------------------------------
# Module-level dialog injection — works for ANY pipeline's module.html.
# Adds one named-NPC-voiced "Table Talk" section (player triggers + NPC
# reactions, visual clues, leaving-the-scene). Self-contained inline styles so
# it renders regardless of which pipeline's CSS is present. Idempotent: skips
# modules that already carry per-scene dialog blocks (e.g. published_pipeline).
# Uses the local model when available, a deterministic NPC-voiced fallback when
# the resource cop defers Ollama under batch load.
# ---------------------------------------------------------------------------

def _npc_context(mission: Dict) -> Dict:
    """Look up the mission's contact + opposing faction for voiced dialog."""
    # Missions frequently carry the literal STRING "None" in opposing_faction
    # (legacy board data / templates) -- treat it like empty so dialog never
    # says "Ask about None".
    _opp = (mission.get("opposing_faction") or "").strip()
    if _opp.lower() in ("none", "n/a", "unknown", "null", "tbd"):
        _opp = ""
    ctx = {
        "contact_name":       (mission.get("contact") or "").strip() or "your contact",
        "contact_role":       "",
        "contact_quote":      "",
        "contact_faction":    (mission.get("faction") or "").strip() or "the faction",
        "antagonist_faction": _opp or "the opposition",
    }
    try:
        from src.db_api import get_npc
        row = get_npc(ctx["contact_name"]) if ctx["contact_name"] != "your contact" else None
        if row:
            ctx["contact_role"]  = str(row.get("rank") or row.get("motivation") or "").strip()[:80]
            ctx["contact_quote"] = str(row.get("quote") or "").strip()[:160]
            if row.get("faction"):
                ctx["contact_faction"] = str(row["faction"]).strip()
    except Exception as e:
        logger.debug(f"[dialogs] NPC lookup skipped: {e}")
    return ctx


def _module_grounding(module_html: str, limit: int = 1400) -> str:
    """Pull briefing + read-aloud text from a module to ground the dialog."""
    chunks: List[str] = []
    bm = re.search(r'[Bb]riefing.*?</div>\s*<div[^>]*>(.*?)</div>', module_html, re.DOTALL)
    if bm:
        chunks.append(_strip_tags(bm.group(1)))
    for m in re.finditer(r'class="read-aloud"[^>]*>(.*?)</div>', module_html, re.DOTALL):
        chunks.append(_strip_tags(m.group(1)))
        if sum(len(c) for c in chunks) > limit:
            break
    text = " ".join(c for c in chunks if c).strip()
    return text[:limit]


def _build_module_dialog_prompt(mission: Dict, npc: Dict, grounding: str) -> str:
    title   = mission.get("title", "the mission")
    contact = npc["contact_name"]
    crole   = f" ({npc['contact_role']})" if npc["contact_role"] else ""
    cvoice  = f' That NPC tends to speak like this: "{npc["contact_quote"]}"' if npc["contact_quote"] else ""
    faction = npc["contact_faction"]
    foe     = npc["antagonist_faction"]
    return f"""Mission: "{title}" (employer: {faction}; opposing side: {foe}).
Primary NPC the party deals with: {contact}{crole}.{cvoice}
What happens in this module: {grounding}

Write table-ready dialog the DM can run when players interact during THIS mission.
Voice every NPC response as a NAMED speaker -- use {contact} for the employer/contact,
and name {foe} for the opposing side. Tie each response to the mission's real stakes.

Output valid JSON only, no markdown:
{{
  "dialogs": [
    {{"trigger": "If players ask/do X", "response": "<named NPC> says or does Y (include a DC or mechanic where useful)"}}
    -- exactly 12 entries covering: pressing {contact} for the real reason behind the job,
       haggling pay, asking what is being withheld, threatening or bribing {contact},
       asking about {foe}, asking about the location, who else was hired, what happens on failure,
       a failed social check, refusing the job, a creative or unexpected approach, asking about risks
  ],
  "visual_clues": [
    {{"element": "specific thing seen/heard/smelled", "detail": "what it reveals and why it matters"}}
    -- exactly 5
  ],
  "leaving_the_scene": {{
    "mood": "one sentence tone as they leave",
    "direction": "one concrete sentence: where they go next",
    "departure_options": ["one atmospheric exit", "a second with a different feel", "a third for parties who linger"],
    "lingers": "one vivid sensory detail that follows them"
  }}
}}"""


def _fallback_module_dialog(mission: Dict, npc: Dict) -> Dict:
    """Deterministic, NPC-voiced dialog when the model is unavailable."""
    c   = npc["contact_name"]
    fac = npc["contact_faction"]
    foe = npc["antagonist_faction"]
    dialogs = [
        {"trigger": f"Press {c} for the real reason behind the job",
         "response": f"{c} gives a partial truth; a DC 14 Insight reveals {fac} stands to lose face if this leaks."},
        {"trigger": "Haggle for more pay",
         "response": f"{c} will not move on coin but offers a {fac} favour or gear instead (DC 13 Persuasion to sweeten it)."},
        {"trigger": "Ask what they are not telling you",
         "response": f"{c} admits {foe} is more involved than the briefing let on -- the job is riskier than posted."},
        {"trigger": f"Threaten or intimidate {c}",
         "response": f"{c} does not rattle (DC 16 Intimidation); push too hard and {fac} marks the party as a liability."},
        {"trigger": f"Ask about {foe}",
         "response": f"{c} sketches {foe}'s strength and one weakness to exploit (DC 12 relevant knowledge for specifics)."},
        {"trigger": "Ask who else was hired",
         "response": f"{c} is cagey; a rival crew may be working the same job (DC 13 Insight to confirm)."},
        {"trigger": "Ask what happens if the party fails",
         "response": f"{c} is blunt: {fac} eats the loss and the party's standing drops -- and {foe} grows bolder."},
        {"trigger": "A social check fails badly",
         "response": f"{c} turns terse and withholds one useful detail until the party proves itself."},
        {"trigger": "Refuse the job or try to walk away",
         "response": f"{c} lets them go, but {fac}'s standing with the party drops and the offer may not return."},
        {"trigger": "Try a creative or unexpected approach",
         "response": f"{c} is intrigued; a clever pitch (DC 13 of the fitting skill) earns a small edge going in."},
    ]
    visual_clues = [
        {"element": f"How {c} carries themselves", "detail": "Signals how serious and well-resourced this job really is."},
        {"element": "The state of the meeting place", "detail": f"Hints at {fac}'s current fortunes and how secret this contract is."},
        {"element": f"What {c} keeps glancing at", "detail": "Betrays the real pressure behind the job -- a deadline, a watcher, or a debt."},
        {"element": f"A detail tied to {foe}", "detail": "A token, mark, or rumour foreshadowing the opposition's involvement."},
        {"element": "Something the briefing left out", "detail": "A DC 13 Perception catches an inconsistency worth questioning."},
    ]
    leaving = {
        "mood": f"The party should leave weighing how much {c} actually told them.",
        "direction": "They head toward the job's first location with the contract's terms fresh.",
        "departure_options": [
            f"They leave clean, {c}'s warning still in their ears.",
            "They linger to press one more question and catch a half-answer.",
            "They exit fast, already arguing over who to trust.",
        ],
        "lingers": f"The exact phrasing of {c}'s last warning.",
    }
    return {"dialogs": dialogs, "visual_clues": visual_clues, "leaving_the_scene": leaving}


def _render_dialog_inline(data: Dict, npc: Dict) -> str:
    """Self-contained, inline-styled dialog section (portable across layouts)."""
    dialogs = [d for d in data.get("dialogs", []) if d.get("trigger") and d.get("response")]
    clues   = [c for c in data.get("visual_clues", []) if c.get("element") and c.get("detail")]
    leaving = data.get("leaving_the_scene") or {}
    if not dialogs and not clues:
        return ""

    contact = _esc(npc.get("contact_name", "the contact"))
    parts = [
        '<div style="margin:22px 0;border-top:3px solid #6b3fa0;padding-top:14px;">',
        f'<h2 style="color:#6b3fa0;margin:0 0 4px;">Table Talk -- Dialog &amp; NPC Reactions</h2>',
        f'<div style="font-size:12px;color:#666;margin-bottom:10px;">Voiced for {contact} and the factions in play. Improvise around these; keep the named voices consistent.</div>',
    ]
    if dialogs:
        rows = "".join(
            f'<tr>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e0d4f0;font-style:italic;color:#3a2060;vertical-align:top;width:42%;">{_esc(d["trigger"])}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e0d4f0;color:#1a1208;vertical-align:top;">{_esc(d["response"])}</td>'
            f'</tr>'
            for d in dialogs
        )
        parts.append(
            '<div style="border:1px solid #8a6abf;border-left:5px solid #6b3fa0;border-radius:6px;padding:12px 16px;margin:12px 0;background:#f7f4fc;">'
            '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
            '<thead><tr>'
            '<th style="background:#6b3fa0;color:#fff;text-align:left;padding:6px 10px;font-size:12px;">If players ask / do...</th>'
            '<th style="background:#6b3fa0;color:#fff;text-align:left;padding:6px 10px;font-size:12px;">NPC or world responds...</th>'
            '</tr></thead>'
            f'<tbody>{rows}</tbody></table></div>'
        )
    if clues:
        items = "".join(
            f'<li style="margin:5px 0;"><strong style="color:#1a4a1a;">{_esc(c["element"])}</strong> -- {_esc(c["detail"])}</li>'
            for c in clues
        )
        parts.append(
            '<div style="border:1px solid #5a8a5a;border-left:5px solid #2a6a2a;border-radius:6px;padding:12px 16px;margin:12px 0;background:#f1f8f1;">'
            '<div style="font-weight:bold;color:#2a5a2a;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-bottom:6px;">Visual Clues &amp; Sensory Details</div>'
            f'<ul style="margin:0;padding-left:18px;font-size:14px;">{items}</ul></div>'
        )
    if leaving.get("mood") or leaving.get("direction"):
        deps = leaving.get("departure_options") or leaving.get("travel_options") or []
        dep_items = "".join(f'<li style="margin:4px 0;">{_esc(x)}</li>' for x in deps if x)
        parts.append(
            '<div style="border:1px solid #c8861a;border-left:5px solid #b8621a;border-radius:6px;padding:12px 16px;margin:12px 0;background:#fff8ee;font-size:14px;">'
            '<div style="font-weight:bold;color:#8a4a10;font-size:11px;letter-spacing:2px;text-transform:uppercase;margin-bottom:8px;">Leaving the Scene</div>'
            + (f'<div style="margin:4px 0;"><strong>Mood:</strong> {_esc(leaving.get("mood",""))}</div>' if leaving.get("mood") else "")
            + (f'<div style="margin:4px 0;"><strong>Next:</strong> {_esc(leaving.get("direction",""))}</div>' if leaving.get("direction") else "")
            + (f'<ul style="margin:6px 0 0;padding-left:18px;">{dep_items}</ul>' if dep_items else "")
            + (f'<div style="margin:6px 0 0;font-style:italic;color:#5a3a10;">Lingers: {_esc(leaving.get("lingers",""))}</div>' if leaving.get("lingers") else "")
            + '</div>'
        )
    parts.append('</div>')
    return "".join(parts)


async def inject_module_dialog(module_html_path: Path, mission: Dict) -> bool:
    """Add a named-NPC-voiced Table Talk section to any module.html. Idempotent.

    Returns True if a section was written. Skips modules that already carry a
    per-scene dialog block (published_pipeline) or that have already been patched.
    """
    try:
        html = module_html_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.debug(f"[dialogs] module dialog skipped (no file): {e}")
        return False
    if 'class="dialog-block"' in html or "Table Talk --" in html:
        return False  # already has dialog (per-scene published, or already patched)

    npc = _npc_context(mission)
    grounding = _module_grounding(html)
    data: Dict = {}
    try:
        raw = await _ask(_build_module_dialog_prompt(mission, npc, grounding), system=_SYSTEM)
        if raw:
            data = _parse_json_safe(raw) or {}
    except Exception as e:
        logger.debug(f"[dialogs] module dialog LLM failed, using fallback: {e}")
    if not data.get("dialogs"):
        data = _fallback_module_dialog(mission, npc)

    section = _render_dialog_inline(data, npc)
    if not section:
        return False

    # Insert before the Mimir reference footer if present, else before </body>.
    anchor = html.find('<div style="margin:24px 0;border-top:3px solid #1a1a2e;')
    if anchor == -1:
        anchor = html.rfind("</body>")
    if anchor == -1:
        patched = html + section
    else:
        patched = html[:anchor] + section + html[anchor:]
    module_html_path.write_text(patched, encoding="utf-8")
    logger.info(f"[dialogs] Table Talk section injected into {module_html_path.name}")
    return True


# ---------------------------------------------------------------------------
# Skill Check Cues — contextual setup + success/fail narration for the checks
# in any pipeline's module. Module-level reference block; LLM-refined when
# available, deterministic per-skill cues otherwise. Idempotent.
# ---------------------------------------------------------------------------

_SKILLS = [
    "Acrobatics", "Animal Handling", "Arcana", "Athletics", "Deception", "History",
    "Insight", "Intimidation", "Investigation", "Medicine", "Nature", "Perception",
    "Performance", "Persuasion", "Religion", "Sleight of Hand", "Stealth", "Survival",
]

# Per-skill default narration: (setup, success, failure). Used as the deterministic
# fallback and as the baseline the LLM refines against.
_SKILL_CUE: Dict[str, tuple] = {
    "Religion":        ("read the rite, relic, or sacred mark for meaning", "the meaning resolves -- they know what is safe to touch and what to avoid", "they misread a sign; a clue is lost or something sacred reacts badly"),
    "Survival":        ("read the ground, the tracks, and the shifting route", "they find the safe line and keep their bearings", "the route turns on them -- lost time, or they stumble into a hazard"),
    "Investigation":   ("work the evidence and piece together what happened", "a concrete lead surfaces that moves the job forward", "the trail muddies; a wrong assumption costs them later"),
    "Perception":      ("scan the scene for what is out of place", "they catch the detail that matters before it bites", "they miss it -- the threat or clue stays hidden for now"),
    "Persuasion":      ("make their case and read how it lands", "the other side gives ground -- access, intel, or a better price", "they overplay it and the door closes a little"),
    "Insight":         ("watch for the tell beneath the words", "they read the truth, or the lie, clearly", "they trust the wrong read and act on it"),
    "Intimidation":    ("apply pressure without making it a fight", "the target folds and gives what was asked", "they push too far and it hardens into hostility"),
    "Stealth":         ("move and act without drawing eyes", "they stay unseen and keep the advantage", "a sound, a shadow, a slip -- someone notices"),
    "Arcana":          ("parse the magical signature at work", "they understand the effect and how to handle it", "they misjudge the magic and it surprises them"),
    "Nature":          ("read the living and natural signs here", "the environment gives up its pattern", "they misjudge it; the wilds or the wildlife react"),
    "Athletics":       ("force the physical problem -- climb, haul, break, or hold", "raw effort wins through", "they fall short -- strain, a slip, or lost ground"),
    "Acrobatics":      ("thread the unstable, the narrow, or the fast", "they keep their feet and their timing", "balance fails at the worst moment"),
    "Sleight of Hand": ("do the delicate work unseen -- lift, plant, or palm", "clean and unnoticed", "fumbled -- it is spotted or damaged"),
    "Medicine":        ("assess and stabilize the body in front of them", "they hold the line on a life, or read the true cause", "they misjudge the injury; it worsens or misleads"),
    "Deception":       ("sell a version of the truth", "it is bought, at least for now", "the seams show and trust drops"),
    "History":         ("recall what the records and old stories hold", "the relevant fact surfaces", "memory fails or misleads them"),
    "Animal Handling": ("read and steady the creature", "it calms or cooperates", "it spooks, balks, or turns on them"),
    "Performance":     ("hold attention and shape the mood", "the room moves with them", "it falls flat or draws the wrong attention"),
}
_SKILL_CUE_DEFAULT = ("attempt the task under pressure", "it works -- they get what they were after", "it fails -- a setback, a cost, or a closed option")

_SKILL_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _SKILLS) + r")\b\s*(?:check)?\s*(?:DC\s*(\d{1,2}))?"
    r"|DC\s*(\d{1,2})\s*\b(" + "|".join(re.escape(s) for s in _SKILLS) + r")\b",
    re.IGNORECASE,
)


def _detect_skill_checks(module_html: str, limit: int = 8) -> List[Dict]:
    """Find distinct skill checks in a module with a short context snippet."""
    text = _strip_tags(module_html)
    found: List[Dict] = []
    seen = set()
    for m in _SKILL_RE.finditer(text):
        skill = (m.group(1) or m.group(4) or "").strip()
        dc    = (m.group(2) or m.group(3) or "").strip()
        if not skill:
            continue
        skill = skill.title() if skill.lower() != "sleight of hand" else "Sleight of Hand"
        key = (skill.lower(), dc)
        if key in seen:
            continue
        seen.add(key)
        a = max(0, m.start() - 70)
        b = min(len(text), m.end() + 70)
        context = re.sub(r"\s+", " ", text[a:b]).strip()
        found.append({"skill": skill, "dc": dc, "context": context})
        if len(found) >= limit:
            break
    return found


def _fallback_skill_cues(checks: List[Dict]) -> List[Dict]:
    out = []
    for c in checks:
        setup, succ, fail = _SKILL_CUE.get(c["skill"], _SKILL_CUE_DEFAULT)
        out.append({**c, "setup": setup, "success": succ, "failure": fail})
    return out


def _build_skill_cues_prompt(mission: Dict, checks: List[Dict]) -> str:
    title = mission.get("title", "the mission")
    listed = "\n".join(
        f'- {c["skill"]}' + (f' DC {c["dc"]}' if c["dc"] else "") + f' | context: {c["context"]}'
        for c in checks
    )
    return f"""Mission: "{title}".
Here are the skill checks that appear in this module, with the surrounding text:
{listed}

For EACH check, write table-ready narration tied to what the check is actually for in THIS mission.
Output valid JSON only, no markdown:
{{
  "checks": [
    {{"skill": "<skill>", "dc": "<dc or empty>",
      "setup": "one sentence: what attempting this check looks like in the fiction",
      "success": "one sentence: what the DM narrates on a success (name the concrete result)",
      "failure": "one sentence: what the DM narrates on a failure (a real cost or setback)"}}
    -- one entry per check above, same order
  ]
}}"""


def _render_skill_cues(cues: List[Dict]) -> str:
    if not cues:
        return ""
    rows = []
    for c in cues:
        head = _esc(c["skill"]) + (f' DC {_esc(c["dc"])}' if c.get("dc") else "")
        ctx  = f' <span style="color:#888;font-weight:normal;font-style:italic;">-- {_esc(c["context"])[:90]}</span>' if c.get("context") else ""
        rows.append(
            '<div style="border:1px solid #b8923a;border-left:5px solid #8a5a1f;border-radius:6px;padding:10px 14px;margin:8px 0;background:#fffdf5;">'
            f'<div style="font-weight:700;color:#7a4a10;margin-bottom:4px;">{head}{ctx}</div>'
            f'<div style="font-size:13px;margin:2px 0;"><strong style="color:#5a4020;">Setup:</strong> {_esc(c.get("setup",""))}</div>'
            f'<div style="font-size:13px;margin:2px 0;"><strong style="color:#2a6a2a;">Success:</strong> {_esc(c.get("success",""))}</div>'
            f'<div style="font-size:13px;margin:2px 0;"><strong style="color:#9a2a2a;">Failure:</strong> {_esc(c.get("failure",""))}</div>'
            '</div>'
        )
    return (
        '<div style="margin:22px 0;border-top:3px solid #8a5a1f;padding-top:14px;">'
        '<h2 style="color:#7a4a10;margin:0 0 4px;">Skill Check Cues</h2>'
        '<div style="font-size:12px;color:#666;margin-bottom:10px;">Contextual setup and success/failure narration for the checks in this module. Improvise around these; keep the named stakes consistent.</div>'
        + "".join(rows) + "</div>"
    )


async def inject_skill_check_cues(module_html_path: Path, mission: Dict) -> bool:
    """Append a contextual Skill Check Cues block to any module.html. Idempotent."""
    try:
        html = module_html_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.debug(f"[dialogs] skill cues skipped (no file): {e}")
        return False
    if "Skill Check Cues" in html:
        return False
    checks = _detect_skill_checks(html)
    if not checks:
        return False

    cues: List[Dict] = []
    try:
        raw = await _ask(_build_skill_cues_prompt(mission, checks), system=_SYSTEM)
        data = _parse_json_safe(raw) if raw else {}
        llm = data.get("checks") if isinstance(data, dict) else None
        if llm:
            # Merge LLM narration onto detected checks (defensive: keep our skill/dc/context)
            for i, c in enumerate(checks):
                src = llm[i] if i < len(llm) else {}
                cues.append({**c,
                             "setup":   str(src.get("setup") or "").strip(),
                             "success": str(src.get("success") or "").strip(),
                             "failure": str(src.get("failure") or "").strip()})
            # backfill any blanks from deterministic cues
            for c in cues:
                d = _SKILL_CUE.get(c["skill"], _SKILL_CUE_DEFAULT)
                c["setup"]   = c["setup"]   or d[0]
                c["success"] = c["success"] or d[1]
                c["failure"] = c["failure"] or d[2]
    except Exception as e:
        logger.debug(f"[dialogs] skill cues LLM failed, using fallback: {e}")
    if not cues:
        cues = _fallback_skill_cues(checks)

    section = _render_skill_cues(cues)
    if not section:
        return False
    anchor = html.find('<div style="margin:24px 0;border-top:3px solid #1a1a2e;')
    if anchor == -1:
        anchor = html.rfind("</body>")
    patched = (html + section) if anchor == -1 else (html[:anchor] + section + html[anchor:])
    module_html_path.write_text(patched, encoding="utf-8")
    logger.info(f"[dialogs] Skill Check Cues injected into {module_html_path.name} ({len(cues)} checks)")
    return True
