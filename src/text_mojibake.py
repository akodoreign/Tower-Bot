"""
Helpers for repairing UTF-8 text that was accidentally decoded as Windows-1252
or Latin-1.

Discord-facing text in this project intentionally uses emoji. This module
restores corrupted emoji/punctuation back to proper Unicode.
"""

from __future__ import annotations

from typing import Any


# Markers that indicate mojibake is present.
# Two corruption paths exist:
#   cp1252 path  — byte 0x80 → € (U+20AC), 0x9C → œ (U+0153), etc.
#   latin-1 path — byte 0x80 → U+0080 (C1 control), 0x9F → U+009F, etc.
# Both paths are covered here.
_MOJIBAKE_MARKERS = (
    # ── cp1252-decoded variants ──────────────────────────────────────────────
    "Ã",       # U+00C3 — start of 2-byte UTF-8 (À–ÿ range)
    "Â",       # U+00C2 — start of 2-byte UTF-8 (non-breaking space etc.)
    "â€",      # â (U+00E2) + € (U+20AC) — start of cp1252 3-byte sequences
    "ðŸ",      # ð (U+00F0) + Ÿ (U+0178) — start of cp1252 4-byte emoji
    "ï¸",      # variation selector via cp1252
    "Ÿ",      # U+0178 standalone corruption
    # ── latin-1-decoded variants (C1 controls: U+0080–U+009F) ────────────────
    "ð\x9f",   # F0 9F — start of 4-byte emoji (📺 🏪 🎯 etc.)
    "â\x80",   # E2 80 — en-dash, em-dash, bullets, curly quotes (U+2000–U+20FF)
    "â\x94",   # E2 94 — box-drawing chars │ ─ ┌ (U+2500–U+257F)
    "â\x9c",   # E2 9C — dingbats ✔ ✨ (U+2700–U+27BF)
    "â\x9a",   # E2 9A — misc symbols ⚔ ⚡ (U+2600–U+26FF)
    "â\x9b",   # E2 9B — misc symbols continued
    "ï\xb8",   # EF B8 — variation selectors (️ U+FE0F)
    "ð\x9f\x93",  # F0 9F 93 — 📺 📰 📣 etc.
    "ð\x9f\x8f",  # F0 9F 8F — 🏪 🏠 etc.
    "ð\x9f\x92",  # F0 9F 92 — 💰 💥 etc.
    "ð\x9f\x8e",  # F0 9F 8E — 🎯 🎭 etc.
)


def _mojibake_score(text: str) -> int:
    return sum(text.count(marker) for marker in _MOJIBAKE_MARKERS) + text.count("�") * 3


def _decode_once(text: str, encoding: str) -> str | None:
    try:
        return text.encode(encoding, errors="strict").decode("utf-8", errors="strict")
    except Exception:
        return None


def _decode_mixed_cp1252_latin1(text: str) -> str | None:
    """Decode text whose mojibake includes raw C1 control characters.

    Python's cp1252 codec cannot encode undefined C1 controls such as U+009D,
    but those bytes do appear when UTF-8 is decoded as Latin-1. Map them back
    to their raw byte value and decode the whole buffer as UTF-8.
    """
    out = bytearray()
    try:
        for ch in text:
            code = ord(ch)
            try:
                out.extend(ch.encode("cp1252"))
            except UnicodeEncodeError:
                if code <= 0xFF:
                    out.append(code)
                else:
                    return None
        return bytes(out).decode("utf-8", errors="strict")
    except Exception:
        return None


def _repair_segment(text: str) -> str:
    """Repair mojibake within a segment that is fully cp1252-encodable."""
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text

    candidates = [text]
    for encoding in ("cp1252", "latin1"):
        decoded = _decode_once(text, encoding)
        if decoded and decoded not in candidates:
            candidates.append(decoded)
    decoded = _decode_mixed_cp1252_latin1(text)
    if decoded and decoded not in candidates:
        candidates.append(decoded)

    # Handle double-corruption: e.g. "ðÅ¸“º" -> "ðŸ\x93º" -> "📺"
    for candidate in list(candidates[1:]):
        for encoding in ("cp1252", "latin1"):
            decoded = _decode_once(candidate, encoding)
            if decoded and decoded not in candidates:
                candidates.append(decoded)
        decoded = _decode_mixed_cp1252_latin1(candidate)
        if decoded and decoded not in candidates:
            candidates.append(decoded)

    original_score = _mojibake_score(text)
    best = min(candidates, key=_mojibake_score)
    return best if _mojibake_score(best) < original_score else text


def _repair_targeted(text: str) -> str:
    """Window-based targeted repair for mixed lines.

    Scans character by character; when a cp1252 multi-byte start byte is found
    (0xC2, 0xC3, 0xE2, 0xEF, 0xF0 as cp1252-decoded codepoints), tries windows
    of 2–10 chars.  Only accepts a repair if the window decodes to fewer chars
    with no remaining markers — preserving surrounding Unicode chars untouched.
    """
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text

    # cp1252 start bytes for multi-byte UTF-8 sequences
    _START = {0xC2, 0xC3, 0xE2, 0xEF, 0xF0}

    result: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch   = text[i]
        code = ord(ch)

        if code in _START:
            fixed: tuple | None = None
            for win_len in range(10, 1, -1):
                window = text[i : i + win_len]
                buf = bytearray()
                ok  = True
                for c in window:
                    c_code = ord(c)
                    try:
                        buf.extend(c.encode("cp1252"))
                    except UnicodeEncodeError:
                        if c_code <= 0xFF:   # C1 control — use raw byte
                            buf.append(c_code)
                        else:
                            ok = False
                            break
                if not ok:
                    continue
                try:
                    decoded = bytes(buf).decode("utf-8", errors="strict")
                except Exception:
                    continue
                # Accept only if compressed (emoji: 4/7 chars → 1/2) and clean
                if len(decoded) < len(window) and not any(m in decoded for m in _MOJIBAKE_MARKERS):
                    fixed = (decoded, win_len)
                    break

            if fixed:
                result.append(fixed[0])
                i += fixed[1]
            else:
                result.append(ch)
                i += 1
        else:
            result.append(ch)
            i += 1

    return "".join(result)


def repair_mojibake(text: str) -> str:
    """Return text with UTF-8-as-cp1252/latin-1 mojibake repaired.

    Handles mixed text where correctly-rendered Unicode emoji coexist with
    corrupted sequences. Repairs segment-by-segment, preserving any chars
    that are not cp1252-encodable (i.e. already correct high-Unicode chars).
    Falls back to targeted window repair for lines that contain both mojibake
    and legitimate extended Unicode (e.g. em-dash alongside a corrupted emoji).
    """
    if not isinstance(text, str) or not text:
        return text
    if not any(marker in text for marker in _MOJIBAKE_MARKERS):
        return text

    # Fast path: entire string is cp1252-encodable — repair as one piece.
    try:
        text.encode("cp1252", errors="strict")
        result = _repair_segment(text)
        if result != text:
            return result
        # Segment repair gave up (score didn't improve) — fall through to targeted
    except UnicodeEncodeError:
        pass

    # Slow path: mixed text — split at genuinely non-cp1252-encodable chars
    # (chars > 0x9F that aren't in cp1252), repair each encodable segment.
    # C1 controls (U+0080–U+009F undefined in cp1252) are kept inside segments
    # so _decode_mixed_cp1252_latin1 can map them back to their raw byte value,
    # keeping multi-byte sequences (e.g. EF B8 8F = variation selector ️) intact.
    segments: list[tuple[bool, str]] = []
    buf: list[str] = []

    for ch in text:
        code = ord(ch)
        if 0x80 <= code <= 0x9F:          # C1 control — keep in repair segment
            buf.append(ch)
            continue
        try:
            ch.encode("cp1252", errors="strict")
            buf.append(ch)
        except UnicodeEncodeError:
            if buf:
                segments.append((True, "".join(buf)))
                buf = []
            segments.append((False, ch))

    if buf:
        segments.append((True, "".join(buf)))

    # Repair each cp1252-encodable segment; fall back to targeted scan if needed
    result_parts: list[str] = []
    for is_cp1252, seg in segments:
        if not is_cp1252:
            result_parts.append(seg)
            continue
        repaired = _repair_segment(seg)
        if repaired == seg and any(marker in seg for marker in _MOJIBAKE_MARKERS):
            repaired = _repair_targeted(seg)
        result_parts.append(repaired)

    return "".join(result_parts)


def repair_payload(value: Any) -> Any:
    """Recursively repair strings inside JSON-like dict/list payloads."""
    if isinstance(value, str):
        return repair_mojibake(value)
    if isinstance(value, list):
        return [repair_payload(item) for item in value]
    if isinstance(value, dict):
        return {key: repair_payload(item) for key, item in value.items()}
    return value
