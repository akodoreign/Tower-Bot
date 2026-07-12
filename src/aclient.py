import os
import discord
import asyncio
import random
from typing import List, Dict, Optional

from src import personas
from src.log import logger
from src.providers import ProviderManager, ProviderType, ModelInfo
from utils.message_utils import send_split_message

from dotenv import load_dotenv

from src.tower_rag import build_context_from_messages  # Tower RAG / campaign_docs
from src.skill_loader import match_skills, format_skills_for_prompt  # Skill system
from src.npc_lookup import get_npc_context_for_prompt  # Quoted NPC name lookup
from src.self_learning import self_learning_loop  # Nightly self-learning
from src.npc_consequence import process_bulletin  # Post-bulletin NPC death/injury scanner
from src.news_feed import (
    generate_bulletin, next_interval_seconds,
    generate_npc_portrait, next_image_interval_seconds,
    check_rift_tick, check_towerbay_tick, check_tia_tick, check_exchange_tick,
    check_weather_tick, check_arena_tick, check_calendar_tick, check_missing_tick,
    check_development_tick, check_council_omen_tick,
    refresh_news_types_if_needed, a1111_lock, _write_memory,
)
from src.city_scene import generate_city_scene
from src.news_integration import post_editorial_bulletin, EditorType
from src.expandable_bulletin import create_bulletin_message, make_bulletin_view
from src.bounty_board import (
    should_post_bounty, generate_bounty_post,
    format_bounty_news_bulletin, check_bounty_expirations,
)
from src.tower_economy import react_to_bulletin, format_towerbay_embeds
from src.bulletin_embeds import wrap_bulletin
from src.npc_lifecycle import run_daily_lifecycle, next_lifecycle_seconds
from src.db_backup import db_backup_loop
from src.ad_feed import check_ad_tick, get_next_ad, generate_dynamic_ad, format_ad_embed
from src.fallen_adventurers import check_fallen_day_tick
from src.character_monitor import run_character_monitor
from src.mission_board import (post_mission, check_expirations, check_claims,
                               check_npc_completions, check_personal_rescissions,
                               next_trickle_seconds, STARTUP_BURST_COUNT, STARTUP_BURST_GAP,
                               post_personal_mission, next_personal_mission_seconds,
                               _load_characters,
                               refresh_mission_types_if_needed,
                               post_calendar_triggered_mission)
from src.faction_calendar import get_pending_mission_spawns, mark_mission_spawned
from src.competitions.post_competition import check_competition_tick
from src.pc_sim import simulate_pc_personal_claims, simulate_pc_personal_completions

load_dotenv()


def _peak_power_delay_seconds() -> int:
    """Seconds until the WEEKDAY 4-9pm peak-rate window ends (0 if outside it).

    Peak electricity pricing (89c/kWh) applies Mon-Fri 16:00-21:00; weekends
    are exempt. A1111 image generation is the biggest discretionary GPU draw,
    so the image loops wait the window out. A small jitter avoids every loop
    waking at exactly 21:00."""
    from datetime import datetime
    now = datetime.now()
    if now.weekday() >= 5:  # Saturday/Sunday exempt
        return 0
    if 16 <= now.hour < 21:
        end = now.replace(hour=21, minute=0, second=0, microsecond=0)
        return max(0, int((end - now).total_seconds())) + random.randint(60, 600)
    return 0


class DiscordClient(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True  # Explicitly enable for on_raw_reaction_add
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
        # Register this loop so Flask Mimir routes submit to it instead of spinning new loops
        try:
            from src.mimir_client import register_bot_loop
            register_bot_loop(asyncio.get_running_loop())
        except Exception:
            pass
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
        # Keep dashboard Discord status fresh independent of mission generation.
        loop = asyncio.get_running_loop()
        loop.create_task(self.discord_heartbeat_loop())
        loop.create_task(self.news_feed_loop())
        loop.create_task(self.mission_board_loop())
        loop.create_task(self.personal_mission_loop())
        loop.create_task(self.log_cleanup_loop())
        loop.create_task(self.chat_reminder_loop())
        loop.create_task(self.story_image_loop())
        loop.create_task(self.npc_portrait_loop())
        loop.create_task(self.npc_lifecycle_loop())
        loop.create_task(self.party_lifecycle_loop())
        loop.create_task(self.character_monitor_loop())
        loop.create_task(self._self_learning_loop())
        loop.create_task(db_backup_loop())
        loop.create_task(self.ad_loop())
        loop.create_task(self.towerbot_world_shop_loop())
        loop.create_task(self.towerbot_item_art_loop())

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

    async def towerbot_world_shop_loop(self):
        """Send queued web-only TowerBot purchase requests to the DM."""
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                from src.towerbot_world_shop import process_purchase_dm_queue
                sent = await process_purchase_dm_queue(self)
                if sent:
                    logger.info(f"TowerBot world shop DM request(s) sent: {sent}")
            except Exception as e:
                logger.warning(f"TowerBot world shop loop error: {e}")
            await asyncio.sleep(60)

    async def towerbot_item_art_loop(self):
        """Generate fallback item art once daily for TowerBot web stock."""
        await self.wait_until_ready()
        await asyncio.sleep(5 * 60)
        while not self.is_closed():
            try:
                from src.towerbot_item_art import run_daily_item_art_if_due
                made = await run_daily_item_art_if_due()
                if made:
                    logger.info(f"TowerBot item art generated: {made}")
            except Exception as e:
                logger.warning(f"TowerBot item art loop error: {e}")
            await asyncio.sleep(30 * 60)

    async def discord_heartbeat_loop(self):
        """Refresh the dashboard Discord heartbeat even when other loops are busy."""
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                from src.db_api import set_global_state
                from datetime import datetime
                await asyncio.to_thread(set_global_state, "discord_status", {
                    "ok": True,
                    "label": str(self.user).split("#")[0] if self.user else "connected",
                    "updated_at": datetime.utcnow().isoformat(),
                })
            except Exception:
                pass
            await asyncio.sleep(60)

    async def _dispatch_calendar_bulletins(self, channel, source_label: str) -> int:
        """Run the calendar bulletin tick and post any due announce/result bulletins."""
        count = 0
        calendar_bulletins = check_calendar_tick()
        for cb in calendar_bulletins:
            await channel.send(
                embed=wrap_bulletin(cb, "calendar"),
                view=make_bulletin_view(
                    cb,
                    "calendar",
                    source_attribution="Faction Calendar",
                ),
            )
            count += 1
            logger.info(
                f"📅 Calendar bulletin posted to #{channel.name} "
                f"(source={source_label})"
            )
        if count == 0:
            logger.debug(f"📅 Calendar tick found no due bulletins (source={source_label})")
        return count

    async def _dispatch_towerbay_tick(self, channel, source_label: str) -> bool:
        """Run TowerBay's cadence tick and post the board when due."""
        try:
            towerbay_bulletin = await check_towerbay_tick(channel=channel)
        except Exception as e:
            logger.exception(f"🏗️ TowerBay tick error (source={source_label}): {e}")
            return False

        if not towerbay_bulletin:
            logger.debug(f"🏗️ TowerBay tick found no due board (source={source_label})")
            return False

        try:
            embeds = format_towerbay_embeds()
            for batch_start in range(0, len(embeds), 10):
                batch = embeds[batch_start:batch_start + 10]
                await channel.send(embeds=batch)
            logger.info(f"🏗️ TowerBay board posted to #{channel.name} ({len(embeds)} embeds)")
            return True
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
            return True

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

        # Economy sidecars may be overdue after restarts; do one immediate cadence pass.
        try:
            channel = self.get_channel(int(discord_channel_id))
            if channel:
                await self._dispatch_towerbay_tick(channel, "startup")
        except Exception as e:
            logger.exception(f"🏗️ Startup TowerBay dispatch error: {e}")

        # Fire 3 quick bulletins on startup to seed the channel, 4 minutes apart
        # (longer gap so Ollama has breathing room between each one)
        for i in range(3):
            await asyncio.sleep(4 * 60)
            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel:
                    # 35% chance to use new agent-based editorial system
                    use_agent_system = random.random() < 0.35
                    
                    if use_agent_system:
                        # Use new agent system (news/gossip/sports with expandable Read More)
                        msg = await post_editorial_bulletin(
                            channel=channel,
                            editor_type=EditorType.RANDOM,
                            write_memory_func=_write_memory,
                        )
                        if msg:
                            logger.info(f"📰 Startup bulletin {i+1}/3 (agent) posted to #{channel.name}")
                            continue  # Skip legacy processing
                    
                    # Legacy system (or agent system failed)
                    bulletin = await generate_bulletin()
                    if bulletin:
                        lines = [l for l in bulletin.splitlines() if l.strip()]
                        preview = "\n".join(lines[:4]) if len(lines) > 4 else bulletin
                        _emb, _view = create_bulletin_message(
                            preview=preview,
                            full_content=bulletin,
                            headline="Undercity Dispatch",
                            bulletin_type="news",
                            source_attribution="TNN Evening Report",
                        )
                        await channel.send(embed=_emb, view=_view)
                        logger.info(f"📰 Startup bulletin {i+1}/3 posted to #{channel.name}")
                        # Scan for NPC death/injury consequences
                        try:
                            changes = process_bulletin(bulletin)
                            for c in changes:
                                logger.info(f"📰 NPC consequence: {c}")
                        except Exception as ce:
                            logger.warning(f"📰 NPC consequence scan error: {ce}")
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

                # 35% chance to use new agent-based editorial system
                use_agent_system = random.random() < 0.35
                bulletin = None
                bulletin_posted = False  # tracks whether ANY bulletin was sent this cycle

                if use_agent_system:
                    # Use new agent system (news/gossip/sports with expandable Read More)
                    msg = await post_editorial_bulletin(
                        channel=channel,
                        editor_type=EditorType.RANDOM,
                        write_memory_func=_write_memory,
                    )
                    if msg:
                        logger.info(f"📰 Agent bulletin posted to #{channel.name}")
                        bulletin_posted = True
                        # bulletin stays None — skip legacy TIA scan for agent posts
                        # (agent bulletins handle their own memory + NPC gossip shouldn't
                        # affect the roster consequence scanner)

                # Legacy system (agent not selected, or agent failed)
                if not bulletin_posted:
                    bulletin = await generate_bulletin()
                    if bulletin:
                        lines = [l for l in bulletin.splitlines() if l.strip()]
                        preview = "\n".join(lines[:4]) if len(lines) > 4 else bulletin
                        _emb, _view = create_bulletin_message(
                            preview=preview,
                            full_content=bulletin,
                            headline="Undercity Dispatch",
                            bulletin_type="news",
                            source_attribution="TNN Evening Report",
                        )
                        await channel.send(embed=_emb, view=_view)
                        logger.info(f"📰 Bulletin posted to #{channel.name}")
                        bulletin_posted = True
                        # Scan for NPC death/injury consequences
                        try:
                            changes = process_bulletin(bulletin)
                            for c in changes:
                                logger.info(f"📰 NPC consequence: {c}")
                        except Exception as ce:
                            logger.warning(f"📰 NPC consequence scan error: {ce}")
                        # TIA news reaction — scan bulletin for market-moving keywords
                        tia_flash = react_to_bulletin(bulletin)
                        if tia_flash:
                            await channel.send(embed=wrap_bulletin(tia_flash, "tia_flash"), view=make_bulletin_view(tia_flash, "tia_flash", source_attribution="TIA Market Flash"))
                            logger.info(f"📊 TIA flash bulletin posted to #{channel.name}")
                    else:
                        logger.warning("📰 generate_bulletin() returned None — legacy bulletin failed this cycle")

                # Rift state machine tick — posts a Rift bulletin if one is due
                rift_bulletin = await check_rift_tick()
                if rift_bulletin:
                    await channel.send(embed=wrap_bulletin(rift_bulletin, "rift"), view=make_bulletin_view(rift_bulletin, "rift", source_attribution="Rift Alert"))
                    logger.info(f"🌀 Rift bulletin posted to #{channel.name}")
                    # Scan rift bulletins too — disasters can kill NPCs
                    try:
                        changes = process_bulletin(rift_bulletin)
                        for c in changes:
                            logger.info(f"🌀 Rift NPC consequence: {c}")
                    except Exception as ce:
                        logger.warning(f"🌀 Rift NPC consequence scan error: {ce}")
                    tia_flash = react_to_bulletin(rift_bulletin)
                    if tia_flash:
                        await channel.send(embed=wrap_bulletin(tia_flash, "tia_flash"), view=make_bulletin_view(tia_flash, "tia_flash", source_attribution="TIA Market Flash"))
                        logger.info(f"📊 TIA flash (rift) posted to #{channel.name}")

                # TowerBay tick — updates bids, posts board once per 24h, posts sold notifications
                await self._dispatch_towerbay_tick(channel, "news_feed_loop")

                # TIA ticker — drifts values, posts every 4h
                tia_bulletin = check_tia_tick()
                if tia_bulletin:
                    await channel.send(embed=wrap_bulletin(tia_bulletin, "tia"), view=make_bulletin_view(tia_bulletin, "tia", source_attribution="Tower Industrial Average"))
                    logger.info(f"📊 TIA ticker posted to #{channel.name}")

                # Dome weather — posts once per 24h
                weather_bulletin = check_weather_tick()
                if weather_bulletin:
                    await channel.send(embed=wrap_bulletin(weather_bulletin, "weather"), view=make_bulletin_view(weather_bulletin, "weather", source_attribution="Dome Weather Service"))
                    logger.info(f"🌫️ Weather report posted to #{channel.name}")

                # Arena match result — posts every 2-3 days when due
                arena_bulletin = await check_arena_tick()
                if arena_bulletin:
                    await channel.send(embed=wrap_bulletin(arena_bulletin, "arena"), view=make_bulletin_view(arena_bulletin, "arena", source_attribution="Arena of Ascendance"))
                    logger.info(f"🏟️ Arena result posted to #{channel.name}")

                # Faction calendar — 48h announcements and event results
                await self._dispatch_calendar_bulletins(channel, "news_feed_loop")

                # Day of the Fallen — fires once per year Jul 8-16, Havel Korin reads the names
                fallen_bulletin = await check_fallen_day_tick()
                if fallen_bulletin:
                    await channel.send(
                        embed=wrap_bulletin(fallen_bulletin, "fallen"),
                        view=make_bulletin_view(fallen_bulletin, "fallen", source_attribution="Wardens of Ash — Captain Havel Korin"),
                    )
                    logger.info(f"🕯️ Day of the Fallen bulletin posted to #{channel.name}")

                # Missing persons — new notices 2-4 days apart, resolutions when expired
                missing_bulletins = await check_missing_tick()
                for mb in missing_bulletins:
                    await channel.send(embed=wrap_bulletin(mb, "missing"), view=make_bulletin_view(mb, "missing", source_attribution="Missing Persons Bureau"))
                    logger.info(f"🔍 Missing persons bulletin posted to #{channel.name}")

                # District development events — construction, openings, relocations (every 2-3 days)
                development_bulletin = await check_development_tick()
                if development_bulletin:
                    await channel.send(
                        embed=wrap_bulletin(development_bulletin, "development"),
                        view=make_bulletin_view(development_bulletin, "development", source_attribution="Undercity Development Office"),
                    )
                    logger.info(f"🏗️ Development bulletin posted to #{channel.name}")

                # Culinary Council omens — fires when LP >= 7, escalates with LP tier
                council_omen = await check_council_omen_tick()
                if council_omen:
                    await channel.send(
                        embed=wrap_bulletin(council_omen, "council"),
                        view=make_bulletin_view(council_omen, "council", source_attribution="City Watch / Warden of Ash"),
                    )
                    logger.info(f"🍽️ Council omen bulletin posted to #{channel.name}")

                # EC/Kharma exchange rate tick — drifts rate, posts every 8h
                exchange_bulletin = check_exchange_tick()
                if exchange_bulletin:
                    await channel.send(embed=wrap_bulletin(exchange_bulletin, "exchange"), view=make_bulletin_view(exchange_bulletin, "exchange", source_attribution="EC/Kharma Exchange"))
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

        # A module-generation task cannot survive a process restart. Clear the
        # persisted active marker so a prior crash/reboot does not wedge the
        # dashboard claim queue forever.
        try:
            from src.db_api import get_global_state, set_global_state
            if get_global_state("module_gen_active"):
                set_global_state("module_gen_active", None)
                logger.info("📖 Cleared stale module_gen_active marker after bot startup")
        except Exception as e:
            logger.warning(f"📖 Could not clear stale module_gen_active marker: {e}")

        # pipeline_busy is written by mark_priority_busy() during generation and
        # persists in DB across process restarts. Always clear it on startup so a
        # crashed pipeline does not block lifecycle and Ollama callers indefinitely.
        try:
            from src.db_api import set_global_state as _sgs
            from src.ollama_busy import unmark_priority_busy
            _sgs("pipeline_busy", {"active": False, "reason": "", "since": ""})
            unmark_priority_busy()
            logger.info("📖 Cleared stale pipeline_busy marker after bot startup")
        except Exception as e:
            logger.warning(f"📖 Could not clear stale pipeline_busy marker: {e}")

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
        tick_count = 0

        logger.info(f"📋 Mission board trickle interval: {trickle_interval // 3600}h {(trickle_interval % 3600) // 60}m")

        while not self.is_closed():
            await asyncio.sleep(60)  # tick every minute
            elapsed += 60
            tick_count += 1

            # Check dashboard module-gen queue (written by /api/claim-mission)
            try:
                from src.db_api import (
                    claim_next_dashboard_claim_job,
                    claim_next_module_generation_job,
                    finish_dashboard_claim_job,
                    finish_module_generation_job,
                    get_global_state,
                    set_global_state,
                )
                _claim_job = claim_next_dashboard_claim_job()
                if _claim_job:
                    try:
                        from src.mission_board import handle_dashboard_claim
                        ok = await handle_dashboard_claim(
                            int(_claim_job["mission_id"]),
                            _claim_job.get("claimer", "DM Dashboard"),
                            client=self,
                        )
                        finish_dashboard_claim_job(int(_claim_job["id"]), bool(ok), "" if ok else "Claim handler returned false")
                    except Exception as _claim_e:
                        finish_dashboard_claim_job(int(_claim_job["id"]), False, str(_claim_e))
                        logger.warning(f"⚔️ Dashboard claim job failed: {_claim_e}")

                # Legacy dashboard_claim_queue via global_state removed — durable job table above handles all claims

                _module_job = None if get_global_state("module_gen_active") else claim_next_module_generation_job()
                if _module_job:
                    set_global_state("module_gen_active", _module_job["mission_id"])
                    from src.mission_board import _load_mission_by_id
                    _mission = _load_mission_by_id(int(_module_job["mission_id"]))
                    if _mission:
                        _claimer = _module_job.get("claimer", "DM Dashboard")
                        _client_ref = self
                        _job_id = int(_module_job["id"])
                        from src.cogs.module_gen import generate_and_post_module
                        async def _run_gen_job(_m=_mission, _c=_claimer, _jid=_job_id):
                            try:
                                set_global_state(f"dashboard_claim_status:{int(_m.get('id') or 0)}", {
                                    "state": "generating",
                                    "mission_id": int(_m.get("id") or 0),
                                    "module_job_id": _jid,
                                    "title": _m.get("title", "Unknown Mission"),
                                    "message": "Module generation is running",
                                })
                                await generate_and_post_module(_m, _c, _client_ref)
                                _updated = _load_mission_by_id(int(_m.get("id") or 0)) or {}
                                finish_module_generation_job(_jid, True, module_slug=_updated.get("module_slug", ""))
                                set_global_state(f"dashboard_claim_status:{int(_m.get('id') or 0)}", {
                                    "state": "complete",
                                    "mission_id": int(_m.get("id") or 0),
                                    "module_job_id": _jid,
                                    "title": _m.get("title", "Unknown Mission"),
                                    "message": "Module generation finished",
                                    "module_slug": _updated.get("module_slug", ""),
                                })
                            except Exception as gen_exc:
                                finish_module_generation_job(_jid, False, str(gen_exc))
                                set_global_state(f"dashboard_claim_status:{int(_m.get('id') or 0)}", {
                                    "state": "failed",
                                    "mission_id": int(_m.get("id") or 0),
                                    "module_job_id": _jid,
                                    "title": _m.get("title", "Unknown Mission"),
                                    "message": f"Module generation failed: {gen_exc}",
                                })
                                logger.exception(f"📖 Module generation job failed for '{_m.get('title', '?')}': {gen_exc}")
                            finally:
                                await asyncio.to_thread(set_global_state, "module_gen_active", None)
                        asyncio.get_running_loop().create_task(_run_gen_job())
                        logger.info(f"📖 Module generation job #{_job_id} started: '{_mission.get('title','?')}' for {_claimer}")
                    else:
                        finish_module_generation_job(int(_module_job["id"]), False, f"Mission ID {_module_job['mission_id']} not found")
                        set_global_state("module_gen_active", None)

                # Legacy module_gen_queue via global_state removed — durable module_generation_jobs table above handles all jobs
            except Exception as _e:
                logger.warning(f"📖 Module gen queue check error: {_e}")

            # Heartbeat — keeps discord_status fresh so the dashboard can detect stale/crashed bot
            try:
                from src.db_api import set_global_state
                from datetime import datetime
                await asyncio.to_thread(set_global_state, "discord_status", {
                    "ok": True,
                    "label": str(self.user).split("#")[0] if self.user else "connected",
                    "updated_at": datetime.utcnow().isoformat(),
                })
            except Exception:
                pass

            # Log board state every 10 minutes
            if tick_count % 10 == 0:
                try:
                    from src.mission_board import _count_active_normal, _count_active_personal, MAX_ACTIVE_NORMAL
                    active = _count_active_normal()
                    time_to_next = max(0, trickle_interval - elapsed)
                    logger.info(
                        f"📋 Board tick [{tick_count}] — "
                        f"active={active}/{MAX_ACTIVE_NORMAL} | "
                        f"next mission in {time_to_next // 3600}h {(time_to_next % 3600) // 60}m | "
                        f"next expiry check in {max(0, expiry_check_interval - (elapsed % expiry_check_interval)) // 60}m"
                    )
                except Exception:
                    pass

            # Check expirations every hour
            if elapsed % expiry_check_interval == 0:
                logger.info("📋 ─── Hourly mission cycle starting ───")
                try:
                    await check_expirations(channel, client=self)
                    logger.info("📋   ✓ check_expirations done")
                    await check_claims(channel, client=self)
                    logger.info("📋   ✓ check_claims done")
                    await check_npc_completions(channel, client=self)
                    logger.info("📋   ✓ check_npc_completions done")
                    await simulate_pc_personal_claims(channel, client=self)
                    logger.info("📋   ✓ simulate_pc_personal_claims done")
                    await simulate_pc_personal_completions(channel, client=self)
                    logger.info("📋   ✓ simulate_pc_personal_completions done")
                    await check_bounty_expirations(channel)
                    logger.info("📋   ✓ check_bounty_expirations done")
                    await check_personal_rescissions(channel, client=self)
                    logger.info("📋   ✓ check_personal_rescissions done")

                    # Calendar-triggered missions — one per hourly cycle max
                    try:
                        pending_cal = get_pending_mission_spawns()
                        if pending_cal:
                            ev = pending_cal[0]  # one per cycle to avoid Ollama pile-on
                            logger.info(
                                f"📅 Calendar mission spawn: '{ev.get('type')}' "
                                f"({ev.get('faction')}) — generating"
                            )
                            spawned = await post_calendar_triggered_mission(channel, ev)
                            if spawned:
                                mark_mission_spawned(ev)
                                logger.info(f"📅   ✓ Calendar mission spawned for '{ev.get('type')}'")
                            else:
                                logger.info(f"📅   ✗ Calendar mission deferred for '{ev.get('type')}'")
                    except Exception as e:
                        logger.exception(f"📅 Calendar mission spawn error: {e}")

                    # Competition brackets — advance rounds, post PC missions, resolve NPC matches
                    try:
                        _news_ch_id = os.getenv("DISCORD_CHANNEL_ID")
                        _news_ch    = self.get_channel(int(_news_ch_id)) if _news_ch_id else None
                        if _news_ch:
                            await check_competition_tick(channel, _news_ch, client=self)
                            logger.info("🏆   ✓ check_competition_tick done")
                        else:
                            logger.debug("🏆 check_competition_tick skipped — no news channel")
                    except Exception as e:
                        logger.exception(f"🏆 Competition tick error: {e}")
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
                        ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
                        ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
                        bounty = await generate_bounty_post(ollama_model, ollama_url)
                        if bounty:
                            msg = await channel.send(bounty["body"])
                            bounty["message_id"] = msg.id
                            logger.info(f"🎯 Bounty posted to mission board: {bounty['id']}")
                            # Fire news bulletin to news channel
                            news_channel_id = os.getenv("DISCORD_CHANNEL_ID")
                            if news_channel_id:
                                news_channel = self.get_channel(int(news_channel_id))
                                if news_channel:
                                    news_text = format_bounty_news_bulletin(bounty)
                                    await news_channel.send(embed=wrap_bulletin(news_text, "bounty"), view=make_bulletin_view(news_text, "bounty", source_attribution="Bounty Board"))
                                    logger.info("🎯 Bounty news bulletin posted to news channel")
                    except Exception as e:
                        logger.exception(f"🎯 Bounty post error: {e}")

            # Post new mission on trickle interval
            if elapsed >= trickle_interval:
                logger.info("📋 ─── Trickle mission trigger ───")
                try:
                    await post_mission(channel)
                    logger.info("📋   ✓ post_mission returned")
                except Exception as e:
                    logger.exception(f"📋 Trickle mission error: {e}")

                # Every trickle also attempt a guild sub-contracted mission
                try:
                    from src.mission_board import post_subcontract_mission
                    posted = await post_subcontract_mission(channel)
                    logger.info(f"📋 [SUB] Subcontract trickle: {'posted' if posted else 'skipped'}")
                except Exception as e:
                    logger.exception(f"📋 [SUB] Subcontract trickle error: {e}")

                # Always reset timer whether we posted or were at cap —
                # but use a shorter retry interval if the board was at cap
                from src.mission_board import _count_active_normal, MAX_ACTIVE_NORMAL
                at_cap = _count_active_normal() >= MAX_ACTIVE_NORMAL
                elapsed = 0
                trickle_interval = 30 * 60 if at_cap else next_trickle_seconds()  # 30min retry if capped, else 6-12h
                if at_cap:
                    logger.info(f"📋 Board at cap ({_count_active_normal()}/{MAX_ACTIVE_NORMAL}) — retrying in 30m")
                else:
                    logger.info(f"📋 Next mission in {trickle_interval // 3600}h {(trickle_interval % 3600) // 60}m")
                tick_count = 0  # reset so next board tick log fires at 10m

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
                    posted = False
                    try:
                        posted = await post_personal_mission(channel, char)
                    except Exception as e:
                        logger.exception(f"📋 Personal mission error ({name}): {e}")
                    if posted:
                        timers[name] = next_personal_mission_seconds()
                        logger.info(f"📋 Next personal mission for {name} in {timers[name]//3600}h")
                    else:
                        timers[name] = 3600  # generation failed — retry in 1h
                        logger.info(f"📋 Personal mission for {name} failed — retrying in 1h")

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
                    await channel.send(embed=wrap_bulletin(reminder, "reminder"), view=make_bulletin_view(reminder, "reminder", source_attribution="Tower Oracle"))
                    logger.info("💬 Chat reminder posted")
            except Exception as e:
                logger.warning(f"💬 Chat reminder error: {e}")

            await asyncio.sleep(random.randint(MIN_INTERVAL, MAX_INTERVAL))

    async def story_image_loop(self):
        """Post a story arc image to the news channel every 5-8 hours.
        Pauses during the weekday 4-9pm peak power window."""
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

        logger.info("🖼️ City scene loop started")

        while not self.is_closed():
            # Weekday 4-9pm peak power window: no discretionary image generation.
            _peak = _peak_power_delay_seconds()
            if _peak:
                logger.info(f"🔌 Peak-rate window (Mon-Fri 4-9pm) — story images resume in {_peak // 60}m")
                await asyncio.sleep(_peak)
                continue
            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel:
                    img_bytes, image_prompt, caption = await generate_city_scene()
                    if img_bytes:
                        file = _discord.File(
                            fp=io.BytesIO(img_bytes),
                            filename="undercity_scene.png"
                        )
                        embed = _discord.Embed(
                            title="📸 The Undercity",
                            description=caption if caption else None,
                            color=_discord.Color.dark_grey()
                        )
                        embed.set_image(url="attachment://undercity_scene.png")
                        await channel.send(file=file, embed=embed)
                        logger.info("🖼️ Story image posted via local A1111")
                        interval = next_image_interval_seconds()
                        logger.info(f"🖼️ Next story image in {interval // 3600}h {(interval % 3600) // 60}m")
                        await asyncio.sleep(interval)
                    else:
                        logger.warning("🖼️ A1111 returned no image — retrying in 10 minutes")
                        await asyncio.sleep(600)
            except Exception as e:
                logger.warning(f"🖼️ Story image loop error: {e!r} — retrying in 10 minutes")
                await asyncio.sleep(600)

    async def npc_portrait_loop(self):
        """Post NPC character bio portraits every 6-9 hours — separate from scene
        images. Pauses during the weekday 4-9pm peak power window. Player-character
        portraits are disabled (news_feed.generate_npc_portrait)."""
        import discord as _discord
        import io, random

        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            return

        await self.wait_until_ready()
        # Stagger from scene loop — wait 45 minutes before first portrait
        await asyncio.sleep(45 * 60)
        logger.info("🎨 NPC portrait loop started")
        startup_calendar_tick_done = False

        # Faction accent colours for embed
        _faction_colours = {
            "iron fang": 0x8B4513, "argent blades": 0x808080,
            "wardens of ash": 0xA0522D, "serpent choir": 0xDAA520,
            "obsidian lotus": 0x4B0082, "glass sigil": 0x4682B4,
            "patchwork saints": 0x8B0000, "adventurer": 0x228B22,
        }

        while not self.is_closed():
            # Weekday 4-9pm peak power window: no discretionary image generation.
            _peak = _peak_power_delay_seconds()
            if _peak:
                logger.info(f"🔌 Peak-rate window (Mon-Fri 4-9pm) — NPC portraits resume in {_peak // 60}m")
                await asyncio.sleep(_peak)
                continue
            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel:
                    img_bytes, npc_data, caption = await generate_npc_portrait()
                    if img_bytes and npc_data:
                        name    = npc_data.get("name", "Unknown")
                        faction = npc_data.get("faction", "Independent")
                        rank    = npc_data.get("rank", "")
                        role    = npc_data.get("role", "")
                        loc     = npc_data.get("location", "")

                        # Pick accent colour
                        _col = 0x555555
                        for _k, _v in _faction_colours.items():
                            if _k in faction.lower():
                                _col = _v
                                break

                        is_alt  = npc_data.get("alt_universe", False)
                        is_pc   = npc_data.get("is_player_char", False)

                        if is_alt:
                            _title = f"🌀 {name} — Alt Universe"
                            _footer = "Tower of Last Chance — What If?"
                        elif faction == "Adventurer":
                            _title = f"⚔️ {name}"
                            _footer = "Tower of Last Chance — Adventurer Portrait"
                        else:
                            _title = f"👤 {name}"
                            _footer = "Tower of Last Chance — Undercity Roster"

                        file = _discord.File(
                            fp=io.BytesIO(img_bytes),
                            filename="npc_portrait.png"
                        )
                        embed = _discord.Embed(title=_title, color=_col)
                        if rank:
                            embed.add_field(name="Rank" if not is_pc else "Level", value=rank, inline=True)
                        if role:
                            embed.add_field(name="Role" if not is_pc else "Class", value=role, inline=True)
                        if faction != "Adventurer":
                            embed.add_field(name="Faction", value=faction, inline=True)
                        if loc:
                            embed.add_field(name="Location", value=loc, inline=True)
                        embed.set_image(url="attachment://npc_portrait.png")
                        embed.set_footer(text=_footer)

                        await channel.send(file=file, embed=embed)
                        logger.info(f"🎨 NPC portrait posted: {name}")
                    else:
                        logger.warning("🎨 NPC portrait generation returned no image")

                    if not startup_calendar_tick_done:
                        try:
                            posted = await self._dispatch_calendar_bulletins(
                                channel,
                                "after_first_npc_portrait",
                            )
                            logger.info(
                                f"📅 Startup calendar tick after first NPC portrait attempt complete "
                                f"({posted} bulletin(s))"
                            )
                        except Exception as cal_exc:
                            logger.warning(
                                f"📅 Startup calendar tick after NPC portrait failed: {cal_exc}"
                            )
                        else:
                            startup_calendar_tick_done = True
            except Exception as e:
                logger.warning(f"🎨 NPC portrait loop error: {e}")
                if not startup_calendar_tick_done:
                    try:
                        channel = self.get_channel(int(discord_channel_id))
                        if channel:
                            posted = await self._dispatch_calendar_bulletins(
                                channel,
                                "after_first_npc_portrait_error",
                            )
                            logger.info(
                                f"📅 Startup calendar tick after NPC portrait error complete "
                                f"({posted} bulletin(s))"
                            )
                            startup_calendar_tick_done = True
                    except Exception as cal_exc:
                        logger.warning(
                            f"📅 Startup calendar tick after NPC portrait error failed: {cal_exc}"
                        )

            # Every 6-9 hours — slowed from 2.5-3.5h on 2026-07-12 (images were
            # posting too fast; A1111 GPU draw matters under peak power pricing).
            interval = random.randint(6 * 3600, 9 * 3600)
            logger.info(f"🎨 Next NPC portrait in {interval // 3600}h {(interval % 3600) // 60}m")
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
        """Run daily NPC lifecycle — new NPC introduced, existing NPCs evolve.
        Also checks the resurrection queue for major NPCs killed in bulletins."""
        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            return

        await self.wait_until_ready()
        # First run: wait 45 minutes so news feed gets several cycles before lifecycle
        # holds Ollama busy. Subsequent runs stay on the normal 20-28h schedule.
        await asyncio.sleep(45 * 60)

        logger.info("🧬 NPC lifecycle loop started")

        while not self.is_closed():
            lifecycle_ran = None
            try:
                channel = self.get_channel(int(discord_channel_id))
                if channel:
                    lifecycle_ran = await run_daily_lifecycle(channel)
            except Exception as e:
                logger.exception(f"🧬 NPC lifecycle error: {e}")

            # Check resurrection queue — major NPCs killed in bulletins come back after 2-7 days
            try:
                from src.npc_consequence import check_resurrection_queue, resurrect_npc
                due = check_resurrection_queue()
                for entry in due:
                    npc = resurrect_npc(entry)
                    if npc:
                        name = npc.get('name', 'Unknown')
                        faction = npc.get('faction', 'Unknown')
                        if npc.get("status") == "lost_to_tower":
                            replacement = npc.get("replacement") or {}
                            replacement_line = ""
                            if replacement:
                                replacement_line = (
                                    f"\nA replacement designation, **{replacement.get('designation', 'UNKNOWN')}**, "
                                    f"has already entered the city records under the name **{replacement.get('name', 'Unknown')}**."
                                )
                            lost_bulletin = (
                                f"🕯️ **CORONER'S OFFICE: Raise Dead Failed.**\n"
                                f"The diamond was purchased. The spell was cast. **{name}** did not return.\n"
                                f"Officials have marked the case as *lost to the Tower*, which is the polite phrase for "
                                f"when the paperwork has no body, no soul, and no appeal window.{replacement_line}"
                            )
                            logger.info(f"🕯️ LOST TO TOWER: {name} ({faction}); replacement={replacement.get('name', '')}")
                            try:
                                channel = self.get_channel(int(discord_channel_id))
                                if channel:
                                    await channel.send(embed=wrap_bulletin(lost_bulletin, "news"), view=make_bulletin_view(lost_bulletin, "news", source_attribution="City Coroner"))
                                    from src.news_feed import _write_memory
                                    _write_memory(lost_bulletin)
                            except Exception as post_err:
                                logger.warning(f"🕯️ Could not post Tower-loss bulletin for {name}: {post_err}")
                            continue
                        logger.info(f"✨ RESURRECTED: {name} ({faction}) returned to active roster")
                        # Post resurrection bulletin to news channel
                        try:
                            channel = self.get_channel(int(discord_channel_id))
                            if channel:
                                res_bulletin = (
                                    f"✨ **BREAKING: {name} Lives.**\n"
                                    f"Reports of {name}'s death appear to have been "
                                    f"greatly exaggerated — or perhaps not exaggerated enough. "
                                    f"The {faction} {'operative' if faction != 'Independent' else 'figure'} "
                                    f"was seen alive in the Undercity today, though details "
                                    f"of their return remain unclear. Divine intervention? "
                                    f"Arcane contingency? The city has questions."
                                )
                                await channel.send(embed=wrap_bulletin(res_bulletin, "news"), view=make_bulletin_view(res_bulletin, "news", source_attribution="TNN"))
                                # Also save to memory so future bulletins know
                                from src.news_feed import _write_memory
                                _write_memory(f"{name} ({faction}) has been resurrected and returned to the Undercity. Previously reported dead.")
                        except Exception as post_err:
                            logger.warning(f"✨ Could not post resurrection bulletin for {name}: {post_err}")
            except Exception as res_err:
                logger.warning(f"🧬 Resurrection queue check error: {res_err}")

            if lifecycle_ran is False:
                retry_seconds = int(os.getenv("NPC_LIFECYCLE_BUSY_RETRY_SECONDS", "3600"))
                logger.info(
                    f"🧬 NPC lifecycle deferred by Ollama busy; retrying in "
                    f"{retry_seconds // 60}m"
                )
                await asyncio.sleep(retry_seconds)
                continue

            interval = next_lifecycle_seconds()
            logger.info(f"🧬 Next NPC lifecycle in {interval // 3600}h {(interval % 3600) // 60}m")
            await asyncio.sleep(interval)

    async def party_lifecycle_loop(self):
        """Daily NPC party lifecycle — crews form, splinter, merge, and keep the
        board's claimant pool alive. Replenishes the LLM-generated crew-name pool
        first, then runs the gated ambient tick. Notable events post a short
        Adventurers Guild registry bulletin so the world visibly moves."""
        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        await self.wait_until_ready()
        # Offset from the NPC lifecycle's 45-minute head start so the two ticks
        # never contend for Ollama back-to-back on boot.
        await asyncio.sleep(90 * 60)

        logger.info("\U0001f6e1️ Party lifecycle loop started")

        while not self.is_closed():
            summary = {}
            try:
                from src.party_lifecycle import party_lifecycle_tick, replenish_party_name_pool, replenish_free_agents
                try:
                    await replenish_party_name_pool(min_free=20)
                except Exception as pool_err:
                    logger.warning(f"\U0001f6e1️ Party name pool replenish skipped: {pool_err}")
                try:
                    await replenish_free_agents(min_free=6, batch=2)
                except Exception as agent_err:
                    logger.warning(f"\U0001f6e1️ Free-agent replenish skipped: {agent_err}")
                summary = party_lifecycle_tick() or {}
            except Exception as e:
                logger.exception(f"\U0001f6e1️ Party lifecycle error: {e}")

            lines = []
            for nm in summary.get("formed", []):
                lines.append(f"A new crew, **{nm}**, registered its charter with the Adventurers Guild.")
            for old, new in summary.get("split", []):
                lines.append(f"**{old}** split; the splinter crew **{new}** filed its own charter.")
            for src_p, into_p in summary.get("merged", []):
                lines.append(f"**{src_p}** folded into **{into_p}** — the registry lists one crew where there were two.")
            if lines and discord_channel_id:
                try:
                    channel = self.get_channel(int(discord_channel_id))
                    if channel:
                        bulletin = "\U0001f4dc **GUILD REGISTRY — CREW MOVEMENTS**\n" + "\n".join(lines)
                        await channel.send(embed=wrap_bulletin(bulletin, "news"),
                                           view=make_bulletin_view(bulletin, "news", source_attribution="Adventurers Guild Registry"))
                        from src.news_feed import _write_memory
                        _write_memory(bulletin)
                except Exception as post_err:
                    logger.warning(f"\U0001f6e1️ Could not post crew-movements bulletin: {post_err}")
            if lines:
                logger.info("\U0001f6e1️ Party lifecycle: " + "; ".join(lines))

            # Daily-ish cadence with jitter, same spirit as the NPC lifecycle.
            interval = random.randint(20 * 3600, 28 * 3600)
            logger.info(f"\U0001f6e1️ Next party lifecycle in {interval // 3600}h {(interval % 3600) // 60}m")
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

    async def _self_learning_loop(self):
        """Wrapper to start the self-learning background loop."""
        await self.wait_until_ready()
        logger.info("🧠 Self-learning loop registered")
        await self_learning_loop(discord_client=self)

    async def ad_loop(self):
        """Post in-world shop advertisements to the news channel every 3 hours."""
        discord_channel_id = os.getenv("DISCORD_CHANNEL_ID")
        if not discord_channel_id:
            logger.info("📢 Ad loop: DISCORD_CHANNEL_ID not set — disabled.")
            return

        await self.wait_until_ready()

        # Initial delay — let the news feed and startup burst run first
        await asyncio.sleep(30 * 60)  # 30 minute initial delay

        logger.info("📢 Ad loop started")

        while not self.is_closed():
            try:
                if check_ad_tick():
                    channel = self.get_channel(int(discord_channel_id))
                    if channel:
                        ad = await get_next_ad()

                        # 20% chance to generate a dynamic ad via Ollama
                        if random.random() < 0.20:
                            try:
                                dynamic_text = await generate_dynamic_ad(
                                    shop_name=ad["shop_name"],
                                    district=ad["district"],
                                    dnd_tags=ad.get("dnd_tags", []),
                                )
                                if dynamic_text:
                                    ad = dict(ad)  # copy so we don't mutate the pool
                                    ad["ad_text"] = dynamic_text
                            except Exception as dyn_err:
                                logger.debug(f"📢 Dynamic ad failed ({dyn_err}) — using static")

                        embed = format_ad_embed(ad)
                        view = make_bulletin_view(
                            ad["ad_text"],
                            bulletin_type=ad.get("bulletin_type", "news"),
                            source_attribution=ad["shop_name"],
                        )
                        await channel.send(embed=embed, view=view)
                        logger.info(f"📢 Ad posted: {ad['shop_name']} ({ad['district']})")
            except Exception as e:
                logger.exception(f"📢 Ad loop error: {e}")

            await asyncio.sleep(30 * 60)  # check every 30 minutes

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
            except discord.InteractionResponded:
                pass  # already deferred/responded — safe to ignore
            except Exception as _e:
                logger.warning("enqueue_message: defer failed (%s) — followup may raise Unknown Interaction", _e)

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

        # Inject matched skills into context
        try:
            matched = match_skills(user_message, self.conversation_history, top_n=3)
            if matched:
                skill_block = format_skills_for_prompt(matched)
                if skill_block:
                    system_context = system_context + "\n\n" + skill_block if system_context else skill_block
                    logger.info(f"🧠 Injected {len(matched)} skills: {[s.title for s in matched]}")
        except Exception as e:
            logger.warning(f"skill_loader: skill injection failed: {e}")

        # Inject NPC context for quoted names (e.g., "Serrik Dhal")
        try:
            npc_context = get_npc_context_for_prompt(user_message)
            if npc_context:
                system_context = system_context + "\n" + npc_context if system_context else npc_context
                logger.info(f"👤 Injected NPC context for quoted names")
        except Exception as e:
            logger.warning(f"npc_lookup: NPC context injection failed: {e}")

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
