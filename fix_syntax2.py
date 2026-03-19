"""
fix_syntax2.py — Replace the broken generate_bulletin() function in news_feed.py.
Run from the bot root:  python fix_syntax2.py
"""
import pathlib, sys

src = pathlib.Path(__file__).parent / "src" / "news_feed.py"
text = src.read_text(encoding="utf-8-sig")

# ── Locate the function ────────────────────────────────────────────────────
FN_SIG = "async def generate_bulletin() -> Optional[str]:"
fn_start = text.find(FN_SIG)
if fn_start == -1:
    print("ERROR: could not find generate_bulletin() — already fixed or different issue")
    sys.exit(1)

# The function ends just before the _DISTRICT_AESTHETICS dict or the
# next top-level `async def` / `# ------` comment block.
# We search for the triple-newline + '# ---' that separates top-level sections.
import re
end_pat = re.compile(r'\n\n\n# -+\n')
m = end_pat.search(text, fn_start + len(FN_SIG))
if not m:
    print("ERROR: could not find the end of generate_bulletin()")
    sys.exit(1)

fn_end = m.start()  # keep the triple-newline + section header
old_fn = text[fn_start:fn_end]
print(f"Found generate_bulletin(): chars {fn_start}–{fn_end} ({len(old_fn)} chars)")

# ── Replacement ────────────────────────────────────────────────────────────
NEW_FN = r'''async def generate_bulletin() -> Optional[str]:
    """
    Generate a fresh bulletin via local Ollama.
    Saves result to news_memory.txt. Returns the bulletin string or None.
    """
    memory = _read_memory()
    prompt = _build_prompt(memory)

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    try:
        import httpx
        payload = {
            "model": ollama_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(ollama_url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        bulletin = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                bulletin = msg.get("content", "").strip()

        if bulletin:
            # Strip any AI assistant preamble mistral might sneak in
            lines = bulletin.splitlines()
            skip_phrases = ("sure", "here's", "here is", "as requested", "certainly", "of course", "i hope", "below is")
            while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip_phrases):
                lines.pop(0)

            # Strip exchange rate lines the AI snuck in
            import re as _re
            _rate_patterns = [
                r'^\**new essence coin prices',
                r'^\d+\s*(kharma|ec)\s*[=:]',
                r'^`\d+\s*(kharma|ec)',
                r'kharma\s*=\s*[\d,.]+\s*ec',
                r'[\d,.]+\s*ec\s*[=:]\s*[\d,.]+\s*kharma',
                r'^-#.*exchange rate',
                r'^\d[\d,.]*(\s*ec|\s*essence coins?)\s+(for|to|gets?|buys?)',
                r'(for only|costs?|price:|pay)\s+\d[\d,.]*\s*(ec|essence coins?)',
            ]
            filtered = []
            for ln in lines:
                ln_lower = ln.lower().strip()
                if any(_re.search(pat, ln_lower) for pat in _rate_patterns):
                    continue
                filtered.append(ln)
            while filtered and not filtered[-1].strip():
                filtered.pop()
            bulletin = "\n".join(filtered).strip()

        if bulletin:
            # Strip inline EC-offer CTAs
            bulletin = _re.sub(
                r'[,.]?\s*\d[\d,.]*\s*(?:ec|essence coins?)\s+(?:for|to|gets?|buys?)[^.\n]*',
                '',
                bulletin,
                flags=_re.IGNORECASE,
            ).strip()

        if bulletin:
            # Strip system prompt echo
            echo_cut = _re.search(
                r'\n\s*---\s*\n+(?:you are the undercity dispatch|task:|write one undercity)',
                bulletin, _re.IGNORECASE
            )
            if echo_cut:
                bulletin = bulletin[:echo_cut.start()].strip()

            # Strip stray timestamp lines
            _ts_lines = bulletin.splitlines()
            while _ts_lines and _re.match(
                r'^-?#?\s*\d{4}-\d{2}-\d{2} \d{2}:\d{2}', _ts_lines[0].strip()
            ):
                _ts_lines.pop(0)
            bulletin = '\n'.join(_ts_lines).strip()

            # Strip Name(#) artifacts
            bulletin = _re.sub(r'(\w[\w\s\']{0,40}?)\(#\)', r'\1', bulletin)
            # Strip fake markdown links
            bulletin = _re.sub(r'\[([^\]\[]{1,80})\]\((?!https?://)[^)]*\)', r'\1', bulletin)
            bulletin = _re.sub(
                r'\[([^\]\[]{1,80})\](?!\()',
                lambda m: m.group(1) if not _re.match(r'\d{4}-\d{2}-\d{2}', m.group(1)) else m.group(0),
                bulletin
            )

        if bulletin:
            # Apply soft death honorifics
            _, _, _, dead_names = _load_npc_status_blocks()
            if dead_names:
                bulletin = _apply_death_honorifics(bulletin, dead_names)

        if bulletin:
            # TNN sign-off
            bulletin = _apply_tnn_signoff(bulletin)

        if bulletin:
            # Editor agent pass
            bulletin = await _edit_bulletin(bulletin, memory)

        if bulletin:
            # CTA / invitation closer strip
            _cta_pats = [
                r'(?i)^.*(?:awaits you|await you|join us|come find us|seek us|look for us)',
                r'(?i)^.*(?:the undercity awaits|the city awaits|the tower awaits)',
                r'(?i)^.*(?:may the (?:spirits|gods|shadows|city)|may fortune|may your path)',
            ]
            _bl = bulletin.splitlines()
            _bl = [ln for ln in _bl if not any(_re.match(p, ln.strip()) for p in _cta_pats)]
            while _bl and not _bl[-1].strip():
                _bl.pop()
            bulletin = '\n'.join(_bl).strip()

        if bulletin:
            # Hard line cap: 8 content lines max
            _bl = bulletin.splitlines()
            _content_lns, _footer = [], None
            for ln in _bl:
                if ln.strip().startswith('-#'):
                    _footer = ln
                else:
                    _content_lns.append(ln)
            _content_lns = _content_lns[:8]
            while _content_lns and not _content_lns[-1].strip():
                _content_lns.pop()
            if _footer:
                _content_lns.append(_footer)
            bulletin = '\n'.join(_content_lns).strip()

        if bulletin:
            _write_memory(bulletin)
            return f"-# \U0001f570\ufe0f {_dual_timestamp()}\n{bulletin}"

    except Exception as e:
        import logging, traceback
        logging.getLogger(__name__).error(
            f"\U0001f4f0 news_feed error: {type(e).__name__}: {e}\n{traceback.format_exc()}"
        )

    return None'''

# ── Write it back ──────────────────────────────────────────────────────────
fixed = text[:fn_start] + NEW_FN + text[fn_end:]

# Quick sanity check — make sure no unterminated strings by looking for the
# specific broken pattern that caused the original crash
if "seek us|look for us)[^" in fixed and "seek us|look for us)'," not in fixed:
    # The broken pattern is still in there — something went wrong
    print("ERROR: broken pattern still detected after replacement — aborting")
    sys.exit(1)

src.write_text(fixed, encoding="utf-8")
print(f"Done. Wrote {len(fixed):,} bytes.")
print("Restart the service: Restart-Service TowerBotService")
