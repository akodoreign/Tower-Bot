import os
import discord
import asyncio
from typing import List, Dict, Optional

from src import personas
from src.log import logger
from src.providers import ProviderManager, ProviderType, ModelInfo
from utils.message_utils import send_split_message

from dotenv import load_dotenv

from src.tower_rag import build_context_from_messages  # Tower RAG / campaign_docs
from src.news_feed import (
    generate_bulletin, next_interval_seconds,
    generate_story_image, next_image_interval_seconds,
    check_rift_tick, check_towerbay_tick, check_tia_tick, check_exchange_tick,
    check_weather_tick, check_arena_tick, check_calendar_tick, check_missing_tick,
    refresh_news_types_if_needed, a1111_lock,
)
from src.bounty_board import (
    should_post_bounty, generate_bounty_post,
    format_bounty_news_bulletin, check_bounty_expirations, _save_bounties, _load_bounties,
)
from src.tower_economy import react_to_bulletin, format_towerbay_embeds
from src.bulletin_embeds import wrap_bulletin
from src.npc_lifecycle import run_daily_lifecycle, next_lifecycle_seconds
from src.character_monitor import run_character_monitor
from src.mission_board import (post_mission, check_expirations, check_claims,
                               check_npc_completions,
                               next_trickle_seconds, STARTUP_BURST_COUNT, STARTUP_BURST_GAP,
                               post_personal_mission, next_personal_mission_seconds,
                               _load_characters, _load_personal_tracker, _save_personal_tracker,
                               refresh_mission_types_if_needed)

load_dotenv()


class DiscordClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        # Slash command tree — created here so setup_hook can sync it
        self.tree = discord.app_commands.CommandTree(self)

        # Initialize provider manager
        self.provider_manager = ProviderManager()

        # Set default provider and model
        default_provider = os.getenv("DEFAULT_PROVIDER", "free")
        try:
            self.provider_manager.set_current_provider(ProviderType(default_provider))
        except ValueError:
            logger.warning(f"Invalid default provider {default_provider}, using free")
            self.provider_manager.set_current_provider(ProviderType.FREE)

        self.current_model = os.getenv("DEFAULT_MODEL", "auto")

        # Conversation management
        self.conversation_history: List[Dict[str, str]] = []
        self.current_channel: Optional[discord.abc.Messageable] = None
        self.current_persona: str = "standard"

        # Bot settings / presence
        self.activity = discord.Activity(
            type=discord.ActivityType.listening,
            name="/chat | /help | /provider",
        )
        self.isPrivate: bool = False
        self.is_replying_all: bool = os.getenv("REPLYING_ALL", "False") == "True"
        self.replying_all_discord_channel_id: Optional[str] = os.getenv(
            "REPLYING_ALL_DISCORD_CHANNEL_ID"
        )

        # Load system prompt (legacy; mostly unused now that Tower RAG is primary)
        config_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        prompt_path = os.path.join(config_dir, "system_prompt.txt")
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                self.starting_prompt = f.read()
        except FileNotFoundError:
            self.starting_prompt = ""
            logger.warning("system_prompt.txt not found")

        # Message queue for rate limiting / background processing
        self.message_queue: asyncio.Queue = asyncio.Queue()

        # Guild ID for sync — set by bot.py before client.run()
        self._sync_guild_id = None

    async def setup_hook(self) -> None:
        """Called once after login, before on_ready. Syncs slash commands to the guild."""
        if self._sync_guild_id:
            guild = discord.Object(id=self._sync_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logger.info(f"✅ setup_hook synced {len(synced)} commands to guild {self._sync_guild_id}")
        else:
            # Fallback: global sync (takes up to 1h to propagate)
            synced = await self.tree.sync()
            logger.info(f"✅ setup_hook synced {len(synced)} commands globally")

    async def process_messages(self):
        """Process queued messages in the background."""
        # Start the news feed loop as a concurrent task
        asyncio.get_event_loop().create_task(self.news_feed_loop())
        # Start the mission board loop
        asyncio.get_event_loop().create_task(self.mission_board_loop())
        # Start the personal mission loop
        asyncio.get_event_loop().create_task(self.personal_mission_loop())
        # Start the log cleanup loop
        asyncio.get_event_loop().create_task(self.log_cleanup_loop())
        # Start the chat reminder loop
        asyncio.get_event_loop().create_task(self.chat_reminder_loop())
        # Start the story image loop
        asyncio.get_event_loop().create_task(self.story_image_loop())
        # Start the NPC lifecycle loop
        asyncio.get_event_loop().create_task(self.npc_lifecycle_loop())
        # Start the character sheet monitor loop
        asyncio.get_event_loop().create_task(self.character_monitor_loop())

        while True:
            if self.current_channel is not None:
                while not self.message_queue.empty():
                    async with self.current_channel.typing():
                        message, user_message = await self.message_queue.get()
                        try:
                            await self.send_message(message, user_message)
                        except Exception as e:
                            logger.exception(f"Error while processing message: {e}")
                        finally:
                            self.message_queue.task_done()
            await asyncio.sleep(1)

    async def news_feed_loop(self):
        """Post hourly mission board bulletins to the default Discord channel."""
        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            logger.info("DISCORD_CHANNEL_ID not set — news feed disabled.")
            return

        # Wait for the bot to fully connect before posting
        await self.wait_until_ready()

        logger.info(f"📰 News feed loop started → channel {discord_channel_id}")

        # Generate fresh news types for today (if stale)
        try:
            await refresh_news_types_if_needed()
        except Exception as e:
            logger.exception(f"📰 News type refresh error: {e}")

        # Fire 3 quick bulletins on startup to seed the channel, 90 seconds apart
        for i in range(3):
            await asyncio.sleep(90)
            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel:
                    bulletin = await generate_bulletin()
                    if bulletin:
                        await channel.send(embed=wrap_bulletin(bulletin, "news"))
                        logger.info(f"📰 Startup bulletin {i+1}/3 posted to #{channel.name}")
            except Exception as e:
                logger.exception(f"📰 Startup bulletin error: {e}")

        # Then settle into normal hourly rotation
        while not self.is_closed():
            interval = next_interval_seconds()
            logger.info(f"📰 Next bulletin in {interval // 60}m {interval % 60}s")
            await asyncio.sleep(interval)

            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel is None:
                    logger.warning(f"📰 News feed: channel {discord_channel_id} not found — skipping.")
                    continue

                bulletin = await generate_bulletin()
                if bulletin:
                    await channel.send(embed=wrap_bulletin(bulletin, "news"))
                    logger.info(f"📰 Bulletin posted to #{channel.name}")
                    # TIA news reaction — scan bulletin for market-moving keywords
                    tia_flash = react_to_bulletin(bulletin)
                    if tia_flash:
                        await channel.send(embed=wrap_bulletin(tia_flash, "tia_flash"))
                        logger.info(f"📊 TIA flash bulletin posted to #{channel.name}")
                else:
                    logger.warning("📰 generate_bulletin() returned None — mission board may be missing.")

                # Rift state machine tick — posts a Rift bulletin if one is due
                rift_bulletin = await check_rift_tick()
                if rift_bulletin:
                    await channel.send(embed=wrap_bulletin(rift_bulletin, "rift"))
                    logger.info(f"🌀 Rift bulletin posted to #{channel.name}")
                    tia_flash = react_to_bulletin(rift_bulletin)
                    if tia_flash:
                        await channel.send(embed=wrap_bulletin(tia_flash, "tia_flash"))
                        logger.info(f"📊 TIA flash (rift) posted to #{channel.name}")

                # TowerBay tick — updates bids, posts board once per 24h, posts sold notifications
                towerbay_bulletin = await check_towerbay_tick(channel=channel)
                if towerbay_bulletin:
                    # Post as color-coded embeds (Discord allows up to 10 embeds per message)
                    try:
                        embeds = format_towerbay_embeds()
                        # Discord max 10 embeds per message — batch if needed
                        for batch_start in range(0, len(embeds), 10):
                            batch = embeds[batch_start:batch_start + 10]
                            await channel.send(embeds=batch)
                        logger.info(f"🏗️ TowerBay board posted to #{channel.name} ({len(embeds)} embeds)")
                    except Exception as embed_err:
                        logger.warning(f"🏗️ TowerBay embed posting failed ({embed_err}) — falling back to text")
                        chunks, current = [], []
                        for line in towerbay_bulletin.splitlines(keepends=True):
                            if sum(len(l) for l in current) + len(line) > 1900:
                                chunks.append("".join(current))
                                current = []
                            current.append(line)
                        if current:
                            chunks.append("".join(current))
                        for chunk in chunks:
                            if chunk.strip():
                                await channel.send(chunk)
                        logger.info(f"🏗️ TowerBay board posted (text fallback, {len(chunks)} chunk(s))")

                # TIA ticker — drifts values, posts every 4h
                tia_bulletin = check_tia_tick()
                if tia_bulletin:
                    await channel.send(embed=wrap_bulletin(tia_bulletin, "tia"))
                    logger.info(f"📊 TIA ticker posted to #{channel.name}")

                # Dome weather — posts once per 24h
                weather_bulletin = check_weather_tick()
                if weather_bulletin:
                    await channel.send(embed=wrap_bulletin(weather_bulletin, "weather"))
                    logger.info(f"🌫️ Weather report posted to #{channel.name}")

                # Arena match result — posts every 2-3 days when due
                arena_bulletin = await check_arena_tick()
                if arena_bulletin:
                    await channel.send(embed=wrap_bulletin(arena_bulletin, "arena"))
                    logger.info(f"🏟️ Arena result posted to #{channel.name}")

                # Faction calendar — 48h announcements and event results
                calendar_bulletins = check_calendar_tick()
                for cb in calendar_bulletins:
                    await channel.send(embed=wrap_bulletin(cb, "calendar"))
                    logger.info(f"📅 Calendar bulletin posted to #{channel.name}")

                # Missing persons — new notices 2-4 days apart, resolutions when expired
                missing_bulletins = await check_missing_tick()
                for mb in missing_bulletins:
                    await channel.send(embed=wrap_bulletin(mb, "missing"))
                    logger.info(f"🔍 Missing persons bulletin posted to #{channel.name}")

                # EC/Kharma exchange rate tick — drifts rate, posts every 8h
                exchange_bulletin = check_exchange_tick()
                if exchange_bulletin:
                    await channel.send(embed=wrap_bulletin(exchange_bulletin, "exchange"))
                    logger.info(f"💱 EC exchange rate posted to #{channel.name}")

                # Daily news type refresh (no-op if already done today)
                try:
                    await refresh_news_types_if_needed()
                except Exception as e:
                    logger.exception(f"📰 News type daily refresh error: {e}")

            except Exception as e:
                logger.exception(f"📰 News feed error: {e}")

    async def mission_board_loop(self):
        """Post missions to the dedicated board channel, check expirations hourly."""
        channel_id = os.getenv("MISSION_BOARD_CHANNEL_ID")
        if not channel_id:
            logger.info("MISSION_BOARD_CHANNEL_ID not set — mission board disabled.")
            return

        await self.wait_until_ready()
        logger.info(f"📋 Mission board loop started → channel {channel_id}")

        channel = self.get_channel(int(channel_id))
        if channel is None:
            logger.warning(f"📋 Mission board: channel {channel_id} not found.")
            return

        # Generate fresh mission types for today (if stale)
        try:
            await refresh_mission_types_if_needed()
        except Exception as e:
            logger.exception(f"📋 Mission type refresh error: {e}")

        # Startup burst — post missions 2 minutes apart
        for i in range(STARTUP_BURST_COUNT):
            await asyncio.sleep(STARTUP_BURST_GAP)
            try:
                await post_mission(channel)
            except Exception as e:
                logger.exception(f"📋 Startup mission {i+1} error: {e}")

        # Trickle loop — new mission every 6-12 hours, expiry check every hour
        expiry_check_interval = 3600  # check expirations every hour
        elapsed = 0
        trickle_interval = next_trickle_seconds()

        while not self.is_closed():
            await asyncio.sleep(60)  # tick every minute
            elapsed += 60

            # Check expirations every hour
            if elapsed % expiry_check_interval == 0:
                try:
                    await check_expirations(channel, client=self)
                    await check_claims(channel, client=self)
                    await check_npc_completions(channel, client=self)
                    await check_bounty_expirations(channel)
                except Exception as e:
                    logger.exception(f"📋 Expiry/claim check error: {e}")

                # Daily mission type refresh (no-op if already done today)
                try:
                    await refresh_mission_types_if_needed()
                except Exception as e:
                    logger.exception(f"📋 Mission type daily refresh error: {e}")

                # Bounty board — max once per 7 days, 15% chance per hourly tick when eligible
                if should_post_bounty():
                    try:
                        ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
                        ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
                        bounty = await generate_bounty_post(ollama_model, ollama_url)
                        if bounty:
                            msg = await channel.send(bounty["body"])
                            bounty["message_id"] = msg.id
                            all_bounties = _load_bounties()
                            all_bounties.append(bounty)
                            _save_bounties(all_bounties)
                            logger.info(f"🎯 Bounty posted to mission board: {bounty['id']}")
                            # Fire news bulletin to news channel
                            news_channel_id = os.getenv("DISCORD_CHANNEL_ID")
                            if news_channel_id:
                                news_channel = self.get_channel(int(news_channel_id))
                                if news_channel:
                                    news_text = format_bounty_news_bulletin(bounty)
                                    await news_channel.send(embed=wrap_bulletin(news_text, "bounty"))
                                    logger.info("🎯 Bounty news bulletin posted to news channel")
                    except Exception as e:
                        logger.exception(f"🎯 Bounty post error: {e}")

            # Post new mission on trickle interval
            if elapsed >= trickle_interval:
                try:
                    await post_mission(channel)
                except Exception as e:
                    logger.exception(f"📋 Trickle mission error: {e}")
                # Always reset timer whether we posted or were at cap —
                # but use a shorter retry interval if the board was at cap
                from src.mission_board import _count_active_normal, MAX_ACTIVE_NORMAL
                at_cap = _count_active_normal() >= MAX_ACTIVE_NORMAL
                elapsed = 0
                trickle_interval = 30 * 60 if at_cap else next_trickle_seconds()  # 30min retry if capped, else 6-12h
                if at_cap:
                    logger.info(f"📋 Board at cap — retrying in 30m")
                else:
                    logger.info(f"📋 Next mission in {trickle_interval // 3600}h {(trickle_interval % 3600) // 60}m")

    async def personal_mission_loop(self):
        """Post personal missions for each character on a 1-3 day rotating schedule."""
        channel_id = os.getenv("MISSION_BOARD_CHANNEL_ID")
        if not channel_id:
            return

        await self.wait_until_ready()
        logger.info("📋 Personal mission loop started")

        channel = self.get_channel(int(channel_id))
        if channel is None:
            logger.warning("📋 Personal mission loop: channel not found")
            return

        # On startup, post one personal mission for each character staggered 3 minutes apart
        characters = _load_characters()
        for i, character in enumerate(characters):
            await asyncio.sleep(180)  # 3 minutes between each startup personal mission
            try:
                await post_personal_mission(channel, character)
            except Exception as e:
                logger.exception(f"📋 Startup personal mission error ({character.get('NAME', '?')}): {e}")

        # Then cycle through all characters, posting a new personal mission every 1-3 days each
        # Build individual next-post timers per character
        from datetime import datetime
        timers = {}
        for char in characters:
            timers[char["NAME"]] = next_personal_mission_seconds()

        elapsed = 0
        while not self.is_closed():
            await asyncio.sleep(60)
            elapsed += 60

            characters = _load_characters()  # reload in case file updated
            for char in characters:
                name = char["NAME"]
                if name not in timers:
                    timers[name] = next_personal_mission_seconds()
                timers[name] -= 60
                if timers[name] <= 0:
                    try:
                        await post_personal_mission(channel, char)
                    except Exception as e:
                        logger.exception(f"📋 Personal mission error ({name}): {e}")
                    timers[name] = next_personal_mission_seconds()
                    logger.info(f"📋 Next personal mission for {name} in {timers[name]//3600}h")

    async def chat_reminder_loop(self):
        """Post a /chat reminder to the main channel every 2-4 hours."""
        import random

        REMINDERS = [
            (
                "👁️ *The Tower is listening.*\n"
                "Use `/chat` to speak with the Oracle — ask about the city, your missions, faction standing, or what stirs in the dark.\n"
                "Need to look up a rule mid-session? `/rules` has you covered."
            ),
            (
                "🗼 The Oracle has not forgotten you.\n"
                "Type `/chat` to ask it anything — lore, rumours, advice, or questions about the Undercity.\n"
                "For spells, features, and game mechanics, try `/rules` — it reads from the same campaign knowledge."
            ),
            (
                "📜 *Contracts shift. Factions move. The city breathes.*\n"
                "Use `/chat` if you want the Tower's perspective on any of it.\n"
                "Use `/rules` if you want the fine print on how something works at the table."
            ),
            (
                "👁️ Something watches from the Tower's upper floors. It will answer if you use `/chat`.\n"
                "It also knows the rulebook. `/rules` — ask it about abilities, conditions, or anything mechanical."
            ),
            (
                "🌑 The Oracle speaks to those who ask.\n"
                "`/chat` — try it between sessions to dig into lore, check in on factions, or just see what it knows about you.\n"
                "`/rules` — try it when you want to double-check a mechanic before the session starts."
            ),
            (
                "🗡️ *You don't have to wait for a session to interact with the Undercity.*\n"
                "Use `/chat` to talk to the Tower Oracle anytime — in-character or out.\n"
                "Use `/rules` to look up spells, class features, conditions, or rulings."
            ),
            (
                "📋 Missions are posted. Factions are watching. The Oracle is awake.\n"
                "Use `/chat` to ask it anything about the world.\n"
                "Use `/rules` to ask it anything about the game."
            ),
            (
                "🔮 Two commands worth knowing:\n"
                "`/chat` — speak directly to the Tower Oracle. Lore, rumours, faction drama, in-character questions.\n"
                "`/rules` — ask about spells, abilities, conditions, or any D&D mechanic. The Oracle knows the books too."
            ),
        ]

        MIN_INTERVAL = 2 * 60 * 60   # 2 hours
        MAX_INTERVAL = 4 * 60 * 60   # 4 hours

        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            return

        await self.wait_until_ready()
        # Initial delay — don't post right on startup alongside the Oracle arrival message
        await asyncio.sleep(random.randint(MIN_INTERVAL, MAX_INTERVAL))

        logger.info("💬 Chat reminder loop started")

        while not self.is_closed():
            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel:
                    reminder = random.choice(REMINDERS)
                    await channel.send(embed=wrap_bulletin(reminder, "reminder"))
                    logger.info("💬 Chat reminder posted")
            except Exception as e:
                logger.warning(f"💬 Chat reminder error: {e}")

            await asyncio.sleep(random.randint(MIN_INTERVAL, MAX_INTERVAL))

    async def story_image_loop(self):
        """Post a story arc image to the news channel once on startup then every 2-4 hours."""
        import discord as _discord
        import io

        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            return

        await self.wait_until_ready()

        # Wait for A1111 to be fully ready — it can take a minute after Stability Matrix launches it
        A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")
        import httpx
        logger.info("🖼️ Waiting for A1111 to be ready...")
        for _ in range(20):  # up to ~3 minutes
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    r = await client.get(f"{A1111_URL}/sdapi/v1/sd-models")
                    if r.status_code == 200:
                        logger.info("🖼️ A1111 is ready — story image loop starting")
                        break
            except Exception:
                pass
            await asyncio.sleep(10)
        else:
            logger.warning("🖼️ A1111 not reachable after 3 minutes — story image loop will try anyway")

        # Disable A1111's built-in watermark stamp once at startup.
        # Doing this here (not per-request via override_settings) avoids 500 errors
        # on A1111 builds that don't support per-request setting overrides.
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{A1111_URL}/sdapi/v1/options",
                    json={"enable_watermark": False},
                )
            logger.info("🖼️ A1111 watermark disabled via /sdapi/v1/options")
        except Exception as _we:
            logger.warning(f"🖼️ Could not disable A1111 watermark: {_we}")

        # Wait for a few bulletins to post first so there's memory to draw from
        await asyncio.sleep(3 * 60)  # 3 minutes after startup

        logger.info("🖼️ Story image loop started")

        while not self.is_closed():
            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel:
                    img_bytes, image_prompt, caption = await generate_story_image()
                    if img_bytes:
                        file = _discord.File(
                            fp=io.BytesIO(img_bytes),
                            filename="undercity_arc.png"
                        )
                        embed = _discord.Embed(
                            title="📸 Undercity — Current Story Arc",
                            description=caption if caption else None,
                            color=_discord.Color.dark_grey()
                        )
                        embed.set_image(url="attachment://undercity_arc.png")
                        await channel.send(file=file, embed=embed)
                        logger.info("🖼️ Story image posted via local A1111")
                    else:
                        logger.warning("🖼️ A1111 returned no image — skipping this cycle")
            except Exception as e:
                logger.warning(f"🖼️ Story image loop error: {e}")

            interval = next_image_interval_seconds()
            logger.info(f"🖼️ Next story image in {interval // 3600}h {(interval % 3600) // 60}m")
            await asyncio.sleep(interval)

    async def character_monitor_loop(self):
        """Poll D&D Beyond every 30 minutes and post character sheet changes to the DM channel."""
        channel_id = int(os.getenv("CHAR_MONITOR_CHANNEL_ID", "1481298967089381457"))
        await self.wait_until_ready()
        # Give the bot a few minutes to settle before the first sweep
        await asyncio.sleep(3 * 60)
        logger.info(f"📊 Character monitor loop starting → channel {channel_id}")

        channel = self.get_channel(channel_id)
        if channel is None:
            logger.warning(f"📊 Character monitor: channel {channel_id} not found — loop disabled")
            return

        # Self-healing loop — restarts on crash instead of dying permanently
        while not self.is_closed():
            try:
                await run_character_monitor(channel)
            except Exception as e:
                logger.exception(f"📊 Character monitor crashed: {e} — restarting in 5 minutes")
                await asyncio.sleep(5 * 60)

    async def npc_lifecycle_loop(self):
        """Run daily NPC lifecycle — new NPC introduced, existing NPCs evolve."""
        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            return

        await self.wait_until_ready()
        # First run: wait 10 minutes after startup so other loops settle first
        await asyncio.sleep(10 * 60)

        logger.info("🧬 NPC lifecycle loop started")

        while not self.is_closed():
            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel:
                    await run_daily_lifecycle(channel)
            except Exception as e:
                logger.exception(f"🧬 NPC lifecycle error: {e}")

            interval = next_lifecycle_seconds()
            logger.info(f"🧬 Next NPC lifecycle in {interval // 3600}h {(interval % 3600) // 60}m")
            await asyncio.sleep(interval)

    async def log_cleanup_loop(self):
        """Trim log files daily — delete lines older than 7 days, cap each file at 50 MB hard limit."""
        import re
        from datetime import datetime, timedelta
        from pathlib import Path

        LOG_DIR        = Path(__file__).resolve().parent.parent / "logs"
        MAX_AGE_DAYS   = 7
        MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB hard cap before trimming regardless of age
        CHECK_INTERVAL = 24 * 60 * 60      # run once per day

        # NSSM timestamps lines like: 2024-01-15 03:22:11: <message>
        TS_PATTERN = re.compile(r'^(\d{4}-\d{2}-\d{2})')

        await self.wait_until_ready()
        logger.info("🧹 Log cleanup loop started (runs daily, 7-day retention)")

        while not self.is_closed():
            await asyncio.sleep(CHECK_INTERVAL)

            if not LOG_DIR.exists():
                continue

            cutoff = datetime.utcnow() - timedelta(days=MAX_AGE_DAYS)
            log_files = list(LOG_DIR.glob("*.log")) + list(LOG_DIR.glob("*.log.*"))

            for log_path in log_files:
                try:
                    size = log_path.stat().st_size

                    # Read all lines
                    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
                    original_count = len(lines)

                    if size > MAX_SIZE_BYTES:
                        # Hard cap: keep only the newest half regardless of age
                        lines = lines[len(lines) // 2:]
                        logger.info(f"🧹 Hard-capped {log_path.name}: {original_count} → {len(lines)} lines")
                    else:
                        # Normal age-based trim: drop lines older than 7 days
                        kept = []
                        for line in lines:
                            m = TS_PATTERN.match(line)
                            if m:
                                try:
                                    line_date = datetime.strptime(m.group(1), "%Y-%m-%d")
                                    if line_date >= cutoff:
                                        kept.append(line)
                                    # else: drop it
                                except ValueError:
                                    kept.append(line)  # unparseable date — keep it
                            else:
                                kept.append(line)  # no timestamp — keep it (continuation line)
                        lines = kept

                    removed = original_count - len(lines)
                    if removed > 0:
                        log_path.write_text("".join(lines), encoding="utf-8")
                        logger.info(f"🧹 Cleaned {log_path.name}: removed {removed} lines ({size // 1024} KB → {log_path.stat().st_size // 1024} KB)")
                    else:
                        logger.info(f"🧹 {log_path.name}: nothing to clean ({size // 1024} KB)")

                except Exception as e:
                    logger.warning(f"🧹 Log cleanup error on {log_path.name}: {e}")

    async def enqueue_message(self, message, prompt: str):
        """
        Enqueue a message for processing.

        - If this is a slash command Interaction, defer only if it hasn't
          already been deferred/responded to.
        - Then push (message, prompt) into the internal message_queue.
        """
        # If this is a slash command Interaction, it will have .response
        if hasattr(message, "response"):
            try:
                # Only defer if no prior response/defer has happened
                if not message.response.is_done():
                    await message.response.defer(ephemeral=self.isPrivate)
            except Exception:
                # Ignore InteractionResponded or any other defer-related issues
                pass

        await self.message_queue.put((message, prompt))

    async def send_message(self, message, user_message: str):
        """Send response to user (slash command or normal message)."""
        if hasattr(message, "user"):  # Slash command Interaction
            author_id = message.user.id
        else:  # Regular message
            author_id = message.author.id

        try:
            response = await self.handle_response(user_message)
            response_content = (
                f'> **{user_message}** - <@{str(author_id)}> \n\n{response}'
            )
            await send_split_message(self, response_content, message)
        except Exception as e:
            logger.exception(f"Error while sending: {e}")
            error_msg = f"❌ Error: {str(e)}"
            if hasattr(message, "followup"):
                # Slash command followup
                await message.followup.send(error_msg)
            else:
                # Normal message in channel
                await message.channel.send(error_msg)

    async def send_start_prompt(self):
        """Send Oracle arrival message to the configured channel."""
        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            logger.info("No DISCORD_CHANNEL_ID set — skipping startup message.")
            return
        try:
            channel = self.get_channel(int(discord_channel_id))
            if channel:
                intro = (
                    "*The Tower stirs. Something ancient fixes its attention on this place.*\n\n"
                    "I am the Oracle. I have watched this city longer than your guilds have had names. "
                    "I speak when there is something worth saying. "
                    "Ask what you will — but choose your questions carefully. "
                    "The Tower remembers everything. "
                    "So do I.\n\n"
                    "*Use `/chat` to speak with me. The mission board is open.*"
                )
                await channel.send(intro)
                logger.info("Startup message sent.")
        except Exception as e:
            logger.exception(f"Error while sending startup message: {e}")

    async def handle_response(self, user_message: str) -> str:
        """
        Generate response using the current provider, with Tower RAG integration.

        Flow:
        - Append user message to conversation_history (user/assistant only).
        - Trim history if needed.
        - Build a strict Tower system context from tower_rag.build_context_from_messages().
        - Send [system_context] + conversation_history to the provider.
        - Append assistant reply to conversation_history.
        """
        # Add user message to history (user/assistant only)
        self.conversation_history.append(
            {"role": "user", "content": user_message}
        )

        # Better conversation management
        MAX_CONVERSATION_LENGTH = int(
            os.getenv("MAX_CONVERSATION_LENGTH", "20")
        )
        CONVERSATION_TRIM_SIZE = int(
            os.getenv("CONVERSATION_TRIM_SIZE", "8")
        )

        if len(self.conversation_history) > MAX_CONVERSATION_LENGTH:
            # Keep system prompts (if any) and recent context
            system_messages = [
                m
                for m in self.conversation_history[:3]
                if m["role"] == "system"
            ]
            recent_messages = self.conversation_history[-CONVERSATION_TRIM_SIZE:]

            if system_messages:
                self.conversation_history = system_messages + recent_messages
            else:
                self.conversation_history = recent_messages

            logger.info(
                f"Trimmed conversation history to {len(self.conversation_history)} messages"
            )

        # Build strict Tower context using RAG over campaign_docs
        system_context = ""
        try:
            system_context = build_context_from_messages(
                self.conversation_history
            )
        except Exception as e:
            logger.exception(f"tower_rag.build_context_from_messages failed: {e}")
            system_context = ""

        # Build message list for the model:
        # - single system message for this turn (Tower context, lore/rules/intent)
        # - followed by the running conversation (user/assistant only)
        messages_for_model: List[Dict[str, str]] = []
        if system_context:
            messages_for_model.append(
                {"role": "system", "content": system_context}
            )

        messages_for_model.extend(self.conversation_history)

        # Get current provider
        provider = self.provider_manager.get_provider()

        try:
            # Generate response
            response = await provider.chat_completion(
                messages=messages_for_model,
                model=self.current_model if self.current_model != "auto" else None,
            )

            # Add assistant response to history
            self.conversation_history.append(
                {"role": "assistant", "content": response}
            )

            return response

        except Exception as e:
            logger.error(f"Provider error: {e}")

            # Try fallback to free provider
            if self.provider_manager.current_provider != ProviderType.FREE:
                logger.info("Falling back to free provider")
                try:
                    free_provider = self.provider_manager.get_provider(
                        ProviderType.FREE
                    )
                    response = await free_provider.chat_completion(
                        messages=messages_for_model,
                        model=None,
                    )
                    self.conversation_history.append(
                        {"role": "assistant", "content": response}
                    )
                    return f"{response}\n\n* *"
                except Exception as fallback_error:
                    logger.error(
                        f"Fallback provider also failed: {fallback_error}"
                    )
                    error_response = (
                        "❌ I'm having trouble processing your request right now. "
                        "Please try again later or contact an administrator."
                    )
                    self.conversation_history.append(
                        {
                            "role": "assistant",
                            "content": error_response,
                        }
                    )
                    return error_response
            else:
                # Already using free provider, return error
                error_response = (
                    "❌ The free provider is currently unavailable. "
                    "Please try again later."
                )
                self.conversation_history.append(
                    {"role": "assistant", "content": error_response}
                )
                return error_response

    async def generate_image(self, prompt: str, model: Optional[str] = None) -> str:
        """Generate image using current provider (or fallback free provider)."""
        provider = self.provider_manager.get_provider()

        if not provider.supports_image_generation():
            provider = self.provider_manager.get_provider(ProviderType.FREE)

        return await provider.generate_image(prompt, model)

    def reset_conversation_history(self):
        """Reset conversation and persona."""
        self.conversation_history = []
        self.current_persona = "standard"
        personas.current_persona = "standard"

    async def switch_persona(self, persona: str, user_id: Optional[str] = None) -> None:
        """Switch to a different persona."""
        self.reset_conversation_history()
        self.current_persona = persona
        personas.current_persona = persona

        # Add persona prompt to conversation (with permission check)
        persona_prompt = personas.get_persona_prompt(persona, user_id)
        self.conversation_history.append(
            {"role": "system", "content": persona_prompt}
        )

        # Get initial response with new persona
        await self.handle_response(
            "Hello! Please confirm you understand your new role."
        )

    def get_current_provider_info(self) -> Dict:
        """Get information about current provider and model."""
        provider = self.provider_manager.get_provider()
        models: List[ModelInfo] = provider.get_available_models()

        return {
            "provider": self.provider_manager.current_provider.value,
            "current_model": self.current_model,
            "available_models": models,
            "supports_images": provider.supports_image_generation(),
        }

    def switch_provider(self, provider_type: ProviderType, model: Optional[str] = None):
        """Switch to a different provider and optionally set model."""
        self.provider_manager.set_current_provider(provider_type)
        if model:
            self.current_model = model
        else:
            provider = self.provider_manager.get_provider()
            models: List[ModelInfo] = provider.get_available_models()
            self.current_model = models[0].name if models else "auto"

    # Helper to match bot.py's discordClient.set_provider(...)
    def set_provider(self, provider_type: ProviderType):
        """Simple wrapper so /setprovider can call discordClient.set_provider()."""
        self.switch_provider(provider_type)


# Create singleton instance
discordClient = DiscordClient()
