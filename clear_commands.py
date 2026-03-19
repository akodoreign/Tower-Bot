import asyncio
import os
import sys
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    print("ERROR: DISCORD_BOT_TOKEN not found in .env")
    sys.exit(1)

import discord

async def clear_all_guild_commands():
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = discord.app_commands.CommandTree(client)

    @client.event
    async def on_ready():
        print(f"Logged in as {client.user} ({client.user.id})")
        print(f"In {len(client.guilds)} guild(s)\n")

        for guild in client.guilds:
            try:
                tree.clear_commands(guild=guild)
                await tree.sync(guild=guild)
                print(f"OK cleared: {guild.name} ({guild.id})")
            except Exception as e:
                print(f"FAILED {guild.name}: {e}")

        try:
            tree.clear_commands(guild=None)
            await tree.sync(guild=None)
            print("OK cleared global commands")
        except Exception as e:
            print(f"FAILED global: {e}")

        print("\nDone. Now run: Restart-Service TowerBotService")
        await client.close()

    await client.start(TOKEN)

asyncio.run(clear_all_guild_commands())
