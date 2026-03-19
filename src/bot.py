"""Tower Bot entry point — loads command modules (cogs) and starts the client.

All slash commands live in src/cogs/*.py.  Each module exposes a
``setup(client)`` function that registers its commands on client.tree.
"""

import os
import asyncio
import importlib

from src.aclient import discordClient
from src.log import logger

# Ordered list of cog modules to load at startup.
COG_MODULES = [
    "src.cogs.chat",
    "src.cogs.character",
    "src.cogs.missions",
    "src.cogs.economy",
    "src.cogs.rules_lookup",
    "src.cogs.images",
    "src.cogs.world",
    "src.cogs.admin",
    "src.cogs.module_gen",
]


def run_discord_bot():
    # Set guild ID so setup_hook knows where to sync
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    if guild_id:
        discordClient._sync_guild_id = int(guild_id)

    # ---- Load all cog modules ----
    for module_path in COG_MODULES:
        try:
            mod = importlib.import_module(module_path)
            mod.setup(discordClient)
            logger.info(f"✅ Loaded cog: {module_path}")
        except Exception as e:
            logger.error(f"❌ Failed to load cog {module_path}: {e}")
            raise

    # ---- on_ready ----
    @discordClient.event
    async def on_ready():
        logger.info("🔥 TOWER BOT STARTED")
        await discordClient.send_start_prompt()
        logger.info(f"✅ Connected as {discordClient.user} in {len(discordClient.guilds)} guild(s)")

        # Re-register persistent views so DM buttons survive restarts
        from src.mission_board import _load_missions, _MissionOutcomeView
        missions = _load_missions()
        view_count = 0
        for i, m in enumerate(missions):
            if m.get("claimed") and not m.get("resolved") and not m.get("npc_claimed"):
                discordClient.add_view(_MissionOutcomeView(mission_index=i))
                view_count += 1
        logger.info(f"🔄 Re-registered {view_count} persistent mission outcome views")

        loop = asyncio.get_event_loop()
        loop.create_task(discordClient.process_messages())
        logger.info(f"{discordClient.user} is now running!")

    # ---- Run ----
    discordClient.run(os.getenv("DISCORD_BOT_TOKEN"))
