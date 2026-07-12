"""
src/tts_engine.py — Text-to-Speech for accessibility.

Uses edge-tts (free Microsoft Edge TTS) to generate audio from bulletin text.
Designed for players who have difficulty reading due to disability.
"""

import asyncio
import logging
import re
from io import BytesIO

logger = logging.getLogger(__name__)

# Per-bulletin-type voices — different Neural voices for distinct tonal flavors.
# Keys are short canonical names; _pick_voice() also matches verbose bulletin_type strings
# (e.g. "human interest piece about a Warrens resident") via keyword scan.
VOICE_MAP: dict[str, str] = {
    "news":         "en-US-GuyNeural",         # Clear, authoritative anchor
    "gossip":       "en-US-AriaNeural",        # Warm, conspiratorial
    "rumour":       "en-US-AriaNeural",        # Same energy as gossip
    "sports":       "en-US-SteffanNeural",     # Energetic, arena hype
    "arena":        "en-US-SteffanNeural",     # Same — arena events
    "weather":      "en-US-JennyNeural",       # Measured, matter-of-fact
    "rift":         "en-US-ChristopherNeural", # Deep, ominous
    "missing":      "en-US-AriaNeural",        # Urgent, concerned
    "bounty":       "en-US-ChristopherNeural", # Gruff, bounty-board gravitas
    "crime":        "en-US-ChristopherNeural", # Same gravitas for crime/incident
    "ad":           "en-US-AndrewNeural",      # Punchy, salesman energy
    "classified":   "en-US-AndrewNeural",      # Classified ads — same energy
    "faction_news": "en-US-GuyNeural",         # Official faction dispatch
    "politics":     "en-US-GuyNeural",         # Council/guild announcements
    "calendar":     "en-US-RogerNeural",       # Formal, civic announcement
    "economy":      "en-US-RogerNeural",       # Market/trade reports
    "human_interest":"en-US-EmmaNeural",       # Warm, personal storytelling
    "divine":       "en-US-ChristopherNeural", # Deep, reverent
    "npc":          "en-US-EricNeural",        # Narrator introducing a new face
    "npc_intro":    "en-US-EricNeural",
    "tia":          "en-US-BrianNeural",       # Tia's distinctive voice
    "tia_flash":    "en-US-BrianNeural",
}
_DEFAULT_VOICE = "en-US-GuyNeural"

# Keyword → voice: scanned in order against the lowercased verbose bulletin_type string.
# First match wins. Covers the long descriptive strings news_feed.py produces.
_KEYWORD_VOICE_RULES: list[tuple[list[str], str]] = [
    # Tia — check first (very specific)
    (["tia"],                                                  "en-US-BrianNeural"),
    # NPC/roster profiles
    (["npc intro", "npc_intro", "npc profile", "roster", "npc spotlight",
      "profile of", "introducing"],                           "en-US-EricNeural"),
    # Arena / combat sports
    (["arena", "duel", "argent blades", "combat sport",
      "tournament", "championship"],                          "en-US-SteffanNeural"),
    # Rift / divine / ominous
    (["rift", "divine", "serpent choir", "religious", "god ",
      "void", "eldritch", "planar", "collapse"],              "en-US-ChristopherNeural"),
    # Missing persons / urgent
    (["missing person", "missing persons", "last seen",
      "whereabouts unknown"],                                  "en-US-AriaNeural"),
    # Bounty / crime / wanted
    (["bounty", "wanted", "crime", "incident", "theft",
      "murder", "assault", "heist", "fugitive", "warrant"],   "en-US-ChristopherNeural"),
    # Gossip / rumour / whisper
    (["gossip", "rumour", "rumor", "whisper", "overheard",
      "word on the street", "scuttlebutt"],                    "en-US-AriaNeural"),
    # Classified ads / commercial
    (["classified ad", "advertisement", "sponsor",
      "commercial", "promotion", "ad "],                      "en-US-AndrewNeural"),
    # Weather / environmental
    (["weather", "environmental", "hazard", "dome pressure",
      "atmospheric", "rain", "storm", "forecast"],            "en-US-JennyNeural"),
    # Economy / trade / market
    (["trade", "market", "price", "commerce", "black market",
      "exchange", "tariff", "guild economy"],                  "en-US-RogerNeural"),
    # Politics / faction / council
    (["political", "council", "faction", "guild spires",
      "fta", "authority", "decree", "ordinance"],             "en-US-GuyNeural"),
    # Human interest — checked after crime/missing to avoid false matches
    (["human interest", "resident", "heartwarming", "community",
      "letter to", "street performer", "coming-of-age",
      "small story", "curiosity", "oddity", "vendor",
      "craftsperson", "coroner", "registry of the dead",
      "inquest", "survivor"],                                  "en-US-EmmaNeural"),
]


def _pick_voice(bulletin_type: str) -> str:
    """
    Select a TTS voice from a bulletin_type string.

    Handles both short canonical keys ("gossip", "tia") and the verbose
    strings news_feed.py generates ("human interest piece about a Warrens resident").
    Exact match on VOICE_MAP first, then keyword scan, then default.
    """
    if not bulletin_type:
        return _DEFAULT_VOICE
    t = bulletin_type.lower().strip()

    # 1. Exact match on VOICE_MAP (handles canonical short keys)
    if t in VOICE_MAP:
        return VOICE_MAP[t]

    # 2. Keyword scan through ordered rules
    for keywords, voice in _KEYWORD_VOICE_RULES:
        if any(kw in t for kw in keywords):
            return voice

    return _DEFAULT_VOICE


def _clean_for_speech(text: str) -> str:
    """Clean bulletin text for natural speech."""
    # Remove Discord markdown
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # **bold**
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # *italic*
    text = re.sub(r'__([^_]+)__', r'\1', text)      # __underline__
    text = re.sub(r'~~([^~]+)~~', r'\1', text)      # ~~strike~~
    text = re.sub(r'`([^`]+)`', r'\1', text)        # `code`
    
    # Remove Discord formatting
    text = re.sub(r'^-#\s*', '', text, flags=re.MULTILINE)  # -# small text
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)   # > quotes
    
    # Remove emoji shortcodes but keep unicode emoji (screen readers handle those)
    text = re.sub(r':[\w_]+:', '', text)
    
    # Clean up TNN signoff for speech
    text = re.sub(r'—\s*Tower News Network.*$', '— Tower News Network', text, flags=re.IGNORECASE)
    text = re.sub(r'—\s*TNN.*$', '— Tower News Network', text, flags=re.IGNORECASE)
    
    # Normalize whitespace
    text = re.sub(r'\n+', '. ', text)
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


async def generate_tts_audio(text: str, bulletin_type: str = "news") -> bytes | None:
    """
    Generate MP3 audio from text using edge-tts.

    Selects a Neural voice based on bulletin_type (see VOICE_MAP).
    Returns MP3 bytes or None on failure.
    """
    try:
        import edge_tts
    except ImportError:
        logger.error("🔊 edge-tts not installed. Run: pip install edge-tts")
        return None

    cleaned = _clean_for_speech(text)
    if not cleaned:
        return None

    voice = _pick_voice(bulletin_type)

    try:
        communicate = edge_tts.Communicate(cleaned, voice)
        
        # Collect audio chunks into BytesIO
        audio_buffer = BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        
        audio_bytes = audio_buffer.getvalue()
        if audio_bytes:
            logger.info(f"🔊 TTS generated: {len(audio_bytes) // 1024}KB [{voice}]")
            return audio_bytes
        else:
            logger.warning("🔊 TTS returned empty audio")
            return None
            
    except Exception as e:
        logger.error(f"🔊 TTS generation failed: {type(e).__name__}: {e}")
        return None
