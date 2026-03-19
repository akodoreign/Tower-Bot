"""
Run this once to fix the unterminated string in news_feed.py:
    python fix_syntax.py
"""
import pathlib, re

path = pathlib.Path(__file__).parent / "src" / "news_feed.py"
text = path.read_text(encoding="utf-8-sig")

# ------------------------------------------------------------------
# The broken block starts at the line containing the unterminated
# raw string and ends at the 'return None' that closes generate_bulletin.
# We identify it by two unique landmarks:
#
#   START: the line with the unterminated pattern (only occurrence)
#   END  : 'return None' immediately followed by blank lines + the
#           "# Story image generation" comment (unique in the file)
# ------------------------------------------------------------------

START_MARKER = "            _cta_patterns = ["
END_MARKER   = "\n\n\n# ---------------------------------------------------------------------------\n# Story image generation"

start_idx = text.find(START_MARKER)
if start_idx == -1:
    print("ERROR: start marker not found — already fixed?")
    raise SystemExit(1)

end_idx = text.find(END_MARKER, start_idx)
if end_idx == -1:
    print("ERROR: end marker not found")
    raise SystemExit(1)

# The chunk we're replacing is from START_MARKER through 'return None'
# (everything up to END_MARKER, which we keep)
broken_chunk = text[start_idx:end_idx]
print(f"Broken chunk found ({len(broken_chunk)} chars):")
print(repr(broken_chunk[:200]))
print("...")

replacement = r"""            _cta_pats = [
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

    return None"""

fixed = text[:start_idx] + replacement + text[end_idx:]
path.write_text(fixed, encoding="utf-8")
print(f"\nDone! Replaced {len(broken_chunk)} chars with {len(replacement)} chars.")
print("Now restart: Restart-Service TowerBotService")
