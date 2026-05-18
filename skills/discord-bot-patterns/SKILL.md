---
name: discord-bot-patterns
description: "Use this skill when writing or modifying Discord bot code using discord.py, especially when working with discord.Client (not commands.Bot), slash commands via app_commands, custom cog/module patterns, UI views, modals, reaction handlers, background task loops, or any Discord API interaction. Also triggers for: embed creation, permission checks, ephemeral responses, deferred interactions, followup messages, persistent views, or DM notifications. Covers the specific patterns used in the Tower of Last Chance bot architecture."
---

# Discord.py Patterns — discord.Client + Custom Cog Architecture

## This Bot Uses discord.Client, NOT commands.Bot

The `DiscordClient` in `src/aclient.py` extends `discord.Client`. This means:
- **No native Cog support** — can't use `@commands.command()` or `class MyCog(commands.Cog)`
- **Command tree is manual** — `self.tree = discord.app_commands.CommandTree(self)`
- **Module loading is custom** — each file in `src/cogs/` exports `setup(client)` which registers commands on `client.tree`

## Slash Command Patterns

### Basic command in a cog module
```python
# src/cogs/mymodule.py
import os
import discord
from discord import app_commands

def setup(client):
    @client.tree.command(name="mycommand", description="What it does")
    @app_commands.describe(arg1="Description of arg1")
    async def mycommand(interaction: discord.Interaction, arg1: str):
        await interaction.response.send_message(f"Got: {arg1}", ephemeral=True)
```

### Command with choices (dropdown)
```python
@client.tree.command(name="example", description="Pick something")
@app_commands.choices(option=[
    app_commands.Choice(name="Display Name", value="internal_value"),
    app_commands.Choice(name="Other Option",  value="other"),
])
async def example(interaction: discord.Interaction, option: str = "default"):
    ...
```

### DM-only command (check DM_USER_ID)
```python
@client.tree.command(name="dmonly", description="[DM only] ...")
async def dmonly(interaction: discord.Interaction):
    dm_id = int(os.getenv("DM_USER_ID", 0))
    if interaction.user.id != dm_id:
        await interaction.response.send_message("❌ DM only.", ephemeral=True)
        return
    ...
```

### Admin-only command (check guild permissions)
```python
@client.tree.command(name="adminonly", description="(Admin) ...")
async def adminonly(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ No permission.", ephemeral=True)
        return
    ...
```

## Interaction Response Patterns

### CRITICAL: You must respond within 3 seconds
Discord kills the interaction if you don't respond within 3 seconds.

**Fast response (< 3s)**:
```python
await interaction.response.send_message("Done!", ephemeral=True)
```

**Slow operation (> 3s) — MUST defer first**:
```python
await interaction.response.defer(ephemeral=True)  # Shows "thinking..."
# ... do slow work (Ollama call, A1111 generation, etc) ...
await interaction.followup.send("Result here", ephemeral=True)
```

**Ephemeral = only visible to the user who ran the command**.

### Sending embeds
```python
embed = discord.Embed(
    title="📊 Title Here",
    description="Body text with **markdown**",
    color=discord.Color.gold(),
)
embed.add_field(name="Field", value="Value", inline=False)
embed.set_footer(text="Footer text")
await interaction.response.send_message(embed=embed, ephemeral=False)
```

### Sending files/images
```python
import io
file = discord.File(io.BytesIO(image_bytes), filename="image.png")
embed = discord.Embed()
embed.set_image(url="attachment://image.png")
await interaction.followup.send(embed=embed, file=file)
```

## UI Views & Buttons

### Ephemeral view with buttons
```python
class MyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)  # 5 minute timeout

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Approved!", view=None)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Rejected!", view=None)

# Usage:
view = MyView()
await interaction.followup.send("Review this:", view=view, ephemeral=True)
```

### Persistent views (survive restarts)
Must use `timeout=None` and unique `custom_id` per button. Re-register in `on_ready`:
```python
class PersistentView(discord.ui.View):
    def __init__(self, data_id: int):
        super().__init__(timeout=None)
        for item in self.children:
            item.custom_id = f"{item.custom_id}_{data_id}"

    @discord.ui.button(label="Click", style=discord.ButtonStyle.primary, custom_id="my_btn")
    async def click(self, interaction, button):
        ...

# In on_ready:
client.add_view(PersistentView(data_id=123))
```

### Modals (text input forms)
```python
class MyModal(discord.ui.Modal, title="Form Title"):
    field1 = discord.ui.TextInput(label="Name", placeholder="Enter name...")
    field2 = discord.ui.TextInput(label="Notes", style=discord.TextStyle.paragraph, required=False)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"Got: {self.field1.value}", ephemeral=True)

# Usage:
await interaction.response.send_modal(MyModal())
```

## Event Handlers

### Reaction handler (for mission claims, etc)
```python
@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == client.user.id:
        return  # Ignore bot's own reactions
    if payload.channel_id != target_channel_id:
        return
    if str(payload.emoji) != "⚔️":
        return

    channel = client.get_channel(payload.channel_id)
    message = await channel.fetch_message(payload.message_id)
    user = await client.fetch_user(payload.user_id)
    # ... handle the reaction
```

### on_message (for replyAll mode)
```python
@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return  # Don't respond to self
    # ... handle message
```

## Background Task Loops

### Pattern used in aclient.py
```python
async def my_loop(self):
    await self.wait_until_ready()  # Wait for bot to connect
    while not self.is_closed():
        try:
            channel = self.get_channel(int(channel_id))
            if channel:
                # ... do work, post to channel
                pass
        except Exception as e:
            logger.exception(f"Loop error: {e}")
        await asyncio.sleep(interval_seconds)
```

### Spawning from process_messages
```python
asyncio.get_event_loop().create_task(self.my_loop())
```

## DM (Direct Message) Notifications
```python
try:
    user = await client.fetch_user(user_id)
    await user.send("Message text")
    # Or with a view:
    await user.send("Message", view=MyView())
except Exception:
    pass  # User may have DMs disabled
```

## Common Pitfalls

1. **Duplicate event handlers**: If two cog modules both register `@client.event async def on_message`, only the LAST one wins. Solution: have only one module handle each event type.
2. **Deferred but no followup**: If you `defer()` but never `followup.send()`, Discord shows "interaction failed".
3. **Double response**: Can't call both `interaction.response.send_message()` AND `interaction.response.defer()` — pick one.
4. **Embed limits**: Title 256 chars, description 4096 chars, field name 256, field value 1024, total embed 6000 chars.
5. **Message limit**: 2000 characters. Split long content into chunks.
6. **Slash command sync**: New commands need `/sync` or bot restart to appear. Guild sync is instant; global sync takes up to 1 hour.
