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

# Voice options - Guy is clear/professional, good for news
TTS_VOICE = "en-US-GuyNeural"


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


async def generate_tts_audio(text: str) -> bytes | None:
    """
    Generate MP3 audio from text using edge-tts.
    
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
    
    try:
        communicate = edge_tts.Communicate(cleaned, TTS_VOICE)
        
        # Collect audio chunks into BytesIO
        audio_buffer = BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])
        
        audio_bytes = audio_buffer.getvalue()
        if audio_bytes:
            logger.info(f"🔊 TTS generated: {len(audio_bytes) // 1024}KB")
            return audio_bytes
        else:
            logger.warning("🔊 TTS returned empty audio")
            return None
            
    except Exception as e:
        logger.error(f"🔊 TTS generation failed: {type(e).__name__}: {e}")
        return None
