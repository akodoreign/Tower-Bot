"""
src/expandable_bulletin.py — Discord Embeds with "Read More" Expansion

Provides expandable bulletins for the news feed:
- 3-line preview in initial embed
- "Read More" button to show full content
- Works with news, gossip, and sports bulletins
- Handles storage of full content for expansion

Architecture:
- BulletinStorage: In-memory cache of full bulletin content
- ExpandButton: Persistent view with Read More button
- create_bulletin_embed: Factory for creating expandable bulletins
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from io import BytesIO

import discord
from discord import ui

from src.tts_engine import generate_tts_audio

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DB persistence helpers — write-through on store, fallback on get
# ---------------------------------------------------------------------------

def _ensure_bulletin_cache_table() -> None:
    """Create bulletin_cache table if it doesn't exist yet."""
    try:
        from src.db_api import raw_execute
        raw_execute("""
            CREATE TABLE IF NOT EXISTS bulletin_cache (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                bulletin_id VARCHAR(16) NOT NULL UNIQUE,
                payload     JSON NOT NULL,
                status      ENUM('active','archived') NOT NULL DEFAULT 'active',
                created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_status (status),
                INDEX idx_created_at (created_at)
            )
        """)
        # Add status column to existing installs that were created without it
        # (MySQL doesn't support ADD COLUMN IF NOT EXISTS — check information_schema instead)
        try:
            from src.db_api import raw_query
            col_exists = raw_query("""
                SELECT 1 FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'bulletin_cache'
                  AND COLUMN_NAME  = 'status'
                LIMIT 1
            """)
            if not col_exists:
                raw_execute("""
                    ALTER TABLE bulletin_cache
                    ADD COLUMN status ENUM('active','archived') NOT NULL DEFAULT 'active',
                    ADD INDEX idx_status (status)
                """)
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"📰 bulletin_cache table init: {e}")


# Auto-create on module load — silently skipped if DB is unavailable
try:
    _ensure_bulletin_cache_table()
except Exception:
    pass


def _db_store_bulletin(
    bulletin_id: str,
    preview: str,
    full_content: str,
    headline: str,
    bulletin_type: str,
    source_attribution: str,
    venue: Optional[str],
    created_at: datetime,
) -> None:
    """Persist a bulletin to the bulletin_cache table (best-effort)."""
    try:
        from src.db_api import raw_execute, raw_query
        payload = json.dumps({
            "preview": preview,
            "full_content": full_content,
            "headline": headline,
            "bulletin_type": bulletin_type,
            "source_attribution": source_attribution,
            "venue": venue,
            "created_at": created_at.isoformat(),
        }, ensure_ascii=False)
        existing = raw_query(
            "SELECT id FROM bulletin_cache WHERE bulletin_id = %s", (bulletin_id,)
        )
        if existing:
            raw_execute(
                "UPDATE bulletin_cache SET payload = %s, created_at = %s WHERE bulletin_id = %s",
                (payload, created_at, bulletin_id),
            )
        else:
            raw_execute(
                "INSERT INTO bulletin_cache (bulletin_id, payload, created_at) VALUES (%s, %s, %s)",
                (bulletin_id, payload, created_at),
            )
    except Exception as e:
        logger.debug(f"📰 bulletin_cache DB write failed (non-fatal): {e}")


def _db_get_bulletin(bulletin_id: str) -> Optional["StoredBulletin"]:
    """Retrieve a bulletin from the DB when the in-memory cache misses."""
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT payload FROM bulletin_cache WHERE bulletin_id = %s LIMIT 1",
            (bulletin_id,),
        )
        if not rows or not rows[0].get("payload"):
            return None
        data = rows[0]["payload"]
        if isinstance(data, str):
            data = json.loads(data)
        return StoredBulletin(
            bulletin_id=bulletin_id,
            preview=data.get("preview", ""),
            full_content=data.get("full_content", ""),
            headline=data.get("headline", ""),
            bulletin_type=data.get("bulletin_type", "news"),
            source_attribution=data.get("source_attribution", "TNN"),
            venue=data.get("venue"),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.now().isoformat())),
        )
    except Exception as e:
        logger.debug(f"📰 bulletin_cache DB read failed (non-fatal): {e}")
        return None


def _db_archive_old_bulletins(cutoff: datetime) -> None:
    """Move bulletins older than cutoff to 'archived' status — never deleted."""
    try:
        from src.db_api import raw_execute
        raw_execute(
            "UPDATE bulletin_cache SET status = 'archived' WHERE status = 'active' AND created_at < %s",
            (cutoff,),
        )
    except Exception as e:
        logger.debug(f"📰 bulletin_cache archive failed (non-fatal): {e}")


def get_archived_headlines(limit: int = 40) -> list[dict]:
    """
    Return recently archived bulletin headlines for anti-repetition checks.

    Each dict has: bulletin_id, headline, bulletin_type, preview, created_at.
    Called by news_feed._build_prompt() to inject into generation prompts.
    """
    try:
        from src.db_api import raw_query
        rows = raw_query(
            """
            SELECT bulletin_id, payload, created_at
            FROM bulletin_cache
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        results = []
        for row in (rows or []):
            data = row.get("payload") or {}
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    data = {}
            results.append({
                "bulletin_id": row.get("bulletin_id", ""),
                "headline": data.get("headline", ""),
                "bulletin_type": data.get("bulletin_type", "news"),
                "preview": data.get("preview", "")[:120],
                "created_at": row.get("created_at", ""),
            })
        return results
    except Exception as e:
        logger.debug(f"📰 get_archived_headlines failed (non-fatal): {e}")
        return []


# ---------------------------------------------------------------------------
# Bulletin Storage — Caches full content for expansion
# ---------------------------------------------------------------------------

@dataclass
class StoredBulletin:
    """A stored bulletin with full content."""
    bulletin_id: str
    preview: str
    full_content: str
    headline: str
    bulletin_type: str  # "news", "gossip", "sports"
    source_attribution: str
    venue: Optional[str]
    created_at: datetime
    expanded_count: int = 0


class BulletinStorage:
    """
    In-memory storage for bulletin full content.
    
    Bulletins are stored by ID and can be retrieved for expansion.
    Old bulletins are cleaned up after 24 hours.
    """
    
    _instance: Optional["BulletinStorage"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._bulletins: Dict[str, StoredBulletin] = {}
            cls._instance._cleanup_task = None
        return cls._instance
    
    def store(
        self,
        preview: str,
        full_content: str,
        headline: str,
        bulletin_type: str,
        source_attribution: str,
        venue: Optional[str] = None,
    ) -> str:
        """Store a bulletin in memory and persist it to the DB."""
        bulletin_id = str(uuid.uuid4())[:8]
        now = datetime.now()

        bulletin = StoredBulletin(
            bulletin_id=bulletin_id,
            preview=preview,
            full_content=full_content,
            headline=headline,
            bulletin_type=bulletin_type,
            source_attribution=source_attribution,
            venue=venue,
            created_at=now,
        )
        self._bulletins[bulletin_id] = bulletin

        # Write-through to DB so buttons survive bot restarts
        _db_store_bulletin(
            bulletin_id, preview, full_content, headline,
            bulletin_type, source_attribution, venue, now,
        )

        # Schedule in-memory cleanup
        self._schedule_cleanup()

        return bulletin_id

    def get(self, bulletin_id: str) -> Optional[StoredBulletin]:
        """Retrieve a bulletin — memory first, DB fallback for post-restart lookups."""
        bulletin = self._bulletins.get(bulletin_id)
        if bulletin:
            bulletin.expanded_count += 1
            return bulletin

        # Memory miss (bot restarted) — try DB
        bulletin = _db_get_bulletin(bulletin_id)
        if bulletin:
            # Warm the in-memory cache so subsequent clicks are instant
            self._bulletins[bulletin_id] = bulletin
            bulletin.expanded_count += 1
            logger.debug(f"📰 Bulletin {bulletin_id} recovered from DB cache")
        return bulletin
    
    def _schedule_cleanup(self):
        """Schedule cleanup of old bulletins."""
        if self._cleanup_task is None or self._cleanup_task.done():
            try:
                loop = asyncio.get_event_loop()
                self._cleanup_task = loop.create_task(self._cleanup_loop())
            except RuntimeError:
                pass  # No event loop available
    
    async def _cleanup_loop(self):
        """Remove bulletins older than 24 hours from memory and DB."""
        await asyncio.sleep(3600)  # Check every hour

        cutoff = datetime.now() - timedelta(hours=24)
        to_remove = [
            bid for bid, b in self._bulletins.items()
            if b.created_at < cutoff
        ]

        for bid in to_remove:
            del self._bulletins[bid]

        if to_remove:
            logger.info(f"📰 Evicted {len(to_remove)} old bulletins from memory cache")

        # Archive in DB (never deleted — kept for anti-repetition lookups)
        _db_archive_old_bulletins(cutoff)


# Global storage instance
_storage = BulletinStorage()


def store_bulletin(
    preview: str,
    full_content: str,
    headline: str,
    bulletin_type: str,
    source_attribution: str,
    venue: Optional[str] = None,
) -> str:
    """Store a bulletin and return its ID."""
    return _storage.store(
        preview=preview,
        full_content=full_content,
        headline=headline,
        bulletin_type=bulletin_type,
        source_attribution=source_attribution,
        venue=venue,
    )


def get_bulletin(bulletin_id: str) -> Optional[StoredBulletin]:
    """Retrieve a stored bulletin."""
    return _storage.get(bulletin_id)


# ---------------------------------------------------------------------------
# Discord UI Components
# ---------------------------------------------------------------------------

class ExpandBulletinView(ui.View):
    """
    Persistent view with a "Read More" button for bulletin expansion.
    
    When clicked, shows the full bulletin content in an ephemeral followup.
    """
    
    def __init__(self, bulletin_id: str, bulletin_type: str):
        # Persistent view — timeout=None means it survives bot restarts
        super().__init__(timeout=None)
        self.bulletin_id = bulletin_id
        self.bulletin_type = bulletin_type
        
        # Create button with custom_id for persistence
        self.read_more_button = ui.Button(
            label="📖 Read More",
            style=self._get_button_style(),
            custom_id=f"bulletin_expand:{bulletin_id}",
        )
        self.read_more_button.callback = self.on_read_more
        self.add_item(self.read_more_button)

        # Accessibility: Listen button for TTS
        self.listen_button = ui.Button(
            label="🔊 Listen",
            style=discord.ButtonStyle.secondary,
            custom_id=f"bulletin_listen:{bulletin_id}",
        )
        self.listen_button.callback = self.on_listen
        self.add_item(self.listen_button)
    
    def _get_button_style(self) -> discord.ButtonStyle:
        """Get button style based on bulletin type."""
        styles = {
            "news": discord.ButtonStyle.primary,
            "gossip": discord.ButtonStyle.secondary,
            "sports": discord.ButtonStyle.success,
        }
        return styles.get(self.bulletin_type, discord.ButtonStyle.primary)
    
    async def on_read_more(self, interaction: discord.Interaction):
        """Handle Read More button click."""
        bulletin = get_bulletin(self.bulletin_id)
        
        if not bulletin:
            await interaction.response.send_message(
                "📰 This bulletin is no longer available.",
                ephemeral=True,
            )
            return
        
        # Create expanded embed
        embed = create_expanded_embed(bulletin)
        
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,  # Only the clicker sees it
        )

    async def on_listen(self, interaction: discord.Interaction):
        """Handle Listen button click — generate TTS audio for accessibility."""
        bulletin = get_bulletin(self.bulletin_id)
        if not bulletin:
            await interaction.response.send_message(
                "🔊 This bulletin is no longer available.",
                ephemeral=True,
            )
            return

        # Defer since TTS generation takes a moment
        await interaction.response.defer(ephemeral=True)

        try:
            audio_bytes = await generate_tts_audio(bulletin.full_content)
            if audio_bytes:
                audio_file = discord.File(
                    BytesIO(audio_bytes),
                    filename=f"bulletin_{self.bulletin_id[:8]}.mp3",
                )
                await interaction.followup.send(
                    content="🔊 Here's the audio version:",
                    file=audio_file,
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "🔊 Sorry, audio generation failed. Please try again.",
                    ephemeral=True,
                )
        except Exception as e:
            logger.error(f"🔊 TTS callback error: {e}")
            await interaction.followup.send(
                "🔊 Sorry, something went wrong generating audio.",
                ephemeral=True,
            )


class ExpandBulletinButton(ui.Button):
    """
    Standalone button for bulletin expansion.
    
    Can be added to any view. Uses custom_id pattern for persistence.
    """
    
    def __init__(self, bulletin_id: str, bulletin_type: str = "news"):
        self.bulletin_id = bulletin_id
        self.bulletin_type = bulletin_type
        
        styles = {
            "news": discord.ButtonStyle.primary,
            "gossip": discord.ButtonStyle.secondary,
            "sports": discord.ButtonStyle.success,
        }
        
        super().__init__(
            label="📖 Read More",
            style=styles.get(bulletin_type, discord.ButtonStyle.primary),
            custom_id=f"bulletin_expand:{bulletin_id}",
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle button click."""
        bulletin = get_bulletin(self.bulletin_id)
        
        if not bulletin:
            await interaction.response.send_message(
                "📰 This bulletin has expired.",
                ephemeral=True,
            )
            return
        
        embed = create_expanded_embed(bulletin)
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ---------------------------------------------------------------------------
# Embed Factories
# ---------------------------------------------------------------------------

def _get_embed_color(bulletin_type: str) -> discord.Color:
    """Get embed color based on bulletin type."""
    colors = {
        "news": discord.Color.blue(),
        "gossip": discord.Color.purple(),
        "sports": discord.Color.gold(),
    }
    return colors.get(bulletin_type, discord.Color.greyple())


def _get_embed_icon(bulletin_type: str) -> str:
    """Get icon emoji based on bulletin type."""
    icons = {
        "news": "📰",
        "gossip": "👁️",
        "sports": "🏟️",
    }
    return icons.get(bulletin_type, "📰")


def create_preview_embed(
    preview: str,
    headline: str,
    bulletin_type: str,
    source_attribution: str,
    venue: Optional[str] = None,
) -> discord.Embed:
    """
    Create the preview embed (3-line version shown in channel).
    """
    icon = _get_embed_icon(bulletin_type)
    color = _get_embed_color(bulletin_type)
    
    # Build title
    if bulletin_type == "gossip":
        title = f"{icon} Whispers in the Dark"
    elif bulletin_type == "sports" and venue:
        title = f"{icon} {venue}"
    elif headline:
        title = f"{icon} {headline}"
    else:
        title = f"{icon} Undercity Dispatch"
    
    embed = discord.Embed(
        title=title,
        description=preview,
        color=color,
    )
    
    embed.set_footer(text=f"{source_attribution} • Click Read More for full story")
    
    return embed


def create_expanded_embed(bulletin: StoredBulletin) -> discord.Embed:
    """
    Create the expanded embed (full content shown on button click).
    """
    icon = _get_embed_icon(bulletin.bulletin_type)
    color = _get_embed_color(bulletin.bulletin_type)
    
    # Build title
    if bulletin.bulletin_type == "gossip":
        title = f"{icon} Whispers in the Dark — Full Story"
    elif bulletin.bulletin_type == "sports" and bulletin.venue:
        title = f"{icon} {bulletin.venue} — Full Coverage"
    elif bulletin.headline:
        title = f"{icon} {bulletin.headline}"
    else:
        title = f"{icon} Undercity Dispatch"
    
    embed = discord.Embed(
        title=title,
        description=bulletin.full_content,
        color=color,
    )
    
    embed.set_footer(text=bulletin.source_attribution)
    embed.timestamp = bulletin.created_at
    
    return embed


def create_bulletin_message(
    preview: str,
    full_content: str,
    headline: str,
    bulletin_type: str,
    source_attribution: str,
    venue: Optional[str] = None,
) -> Tuple[discord.Embed, ui.View]:
    """
    Create a complete bulletin message with embed and Read More button.
    
    Returns:
        (embed, view) tuple ready to be sent to Discord
    """
    # Store the full content
    bulletin_id = store_bulletin(
        preview=preview,
        full_content=full_content,
        headline=headline,
        bulletin_type=bulletin_type,
        source_attribution=source_attribution,
        venue=venue,
    )
    
    # Create preview embed
    embed = create_preview_embed(
        preview=preview,
        headline=headline,
        bulletin_type=bulletin_type,
        source_attribution=source_attribution,
        venue=venue,
    )
    
    # Create view with Read More button
    view = ExpandBulletinView(bulletin_id, bulletin_type)
    
    return embed, view


# ---------------------------------------------------------------------------
# Persistent View Registration
# ---------------------------------------------------------------------------

def setup_persistent_views(bot: discord.Client):
    """
    Register persistent views for bulletin expansion.
    
    Call this in bot setup to restore buttons after restart.
    """
    # We use a generic handler since we can't pre-register all bulletin IDs
    pass  # View persistence handled by custom_id pattern


async def handle_bulletin_interaction(interaction: discord.Interaction):
    """
    Handle bulletin expand and listen interactions.
    
    Called from bot's on_interaction event for bulletin_expand: and bulletin_listen: custom_ids.
    """
    if not interaction.data:
        return
    
    custom_id = interaction.data.get("custom_id", "")
    
    # Handle Read More button
    if custom_id.startswith("bulletin_expand:"):
        bulletin_id = custom_id.replace("bulletin_expand:", "")
        bulletin = get_bulletin(bulletin_id)
        if not bulletin:
            await interaction.response.send_message(
                "📰 This bulletin has expired.",
                ephemeral=True,
            )
            return
        embed = create_expanded_embed(bulletin)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Handle Listen button (TTS accessibility)
    if custom_id.startswith("bulletin_listen:"):
        bulletin_id = custom_id.replace("bulletin_listen:", "")
        bulletin = get_bulletin(bulletin_id)
        if not bulletin:
            await interaction.response.send_message(
                "🔊 This bulletin is no longer available.",
                ephemeral=True,
            )
            return
        
        await interaction.response.defer(ephemeral=True)
        try:
            audio_bytes = await generate_tts_audio(bulletin.full_content)
            if audio_bytes:
                audio_file = discord.File(
                    BytesIO(audio_bytes),
                    filename=f"bulletin_{bulletin_id[:8]}.mp3",
                )
                await interaction.followup.send(
                    content="🔊 Here's the audio version:",
                    file=audio_file,
                    ephemeral=True,
                )
            else:
                await interaction.followup.send(
                    "🔊 Sorry, audio generation failed. Please try again.",
                    ephemeral=True,
                )
        except Exception as e:
            logger.error(f"🔊 TTS handler error: {e}")
            await interaction.followup.send(
                "🔊 Sorry, something went wrong generating audio.",
                ephemeral=True,
            )
        return


# ---------------------------------------------------------------------------
# Integration Helper
# ---------------------------------------------------------------------------

async def post_expandable_bulletin(
    channel: discord.TextChannel,
    preview: str,
    full_content: str,
    headline: str,
    bulletin_type: str,
    source_attribution: str,
    venue: Optional[str] = None,
) -> Optional[discord.Message]:
    """
    Post an expandable bulletin to a channel.
    
    Convenience function that handles creation and sending.
    """
    try:
        embed, view = create_bulletin_message(
            preview=preview,
            full_content=full_content,
            headline=headline,
            bulletin_type=bulletin_type,
            source_attribution=source_attribution,
            venue=venue,
        )
        
        return await channel.send(embed=embed, view=view)
    
    except Exception as e:
        logger.error(f"Failed to post expandable bulletin: {e}")
        return None
