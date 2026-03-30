"""Skills cog — /skills command for inspecting the bot's skill library."""

import os
import discord
from discord import app_commands
from typing import Optional

from src.log import logger
from src.skill_loader import get_skill_inventory, get_skill_body, load_skills, SKILLS_DIR


def setup(client):
    """Register skills commands on the client's command tree."""

    @client.tree.command(
        name="skills",
        description="View the Tower's learned skills and knowledge base.",
    )
    @app_commands.describe(
        action="What to do: list all skills, view one in detail, or check stats",
        skill_name="(For 'view') The filename of the skill to inspect",
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="📋 List all skills", value="list"),
        app_commands.Choice(name="🔍 View a skill", value="view"),
        app_commands.Choice(name="📊 Stats", value="stats"),
        app_commands.Choice(name="🔄 Reload", value="reload"),
    ])
    async def skills_cmd(
        interaction: discord.Interaction,
        action: str = "list",
        skill_name: Optional[str] = None,
    ):
        # DM-only for reload
        if action == "reload":
            dm_id = int(os.getenv("DM_USER_ID", "0"))
            if interaction.user.id != dm_id:
                await interaction.response.send_message(
                    "❌ Only the DM can reload skills.", ephemeral=True
                )
                return

            load_skills(force=True)
            inventory = get_skill_inventory()
            await interaction.response.send_message(
                f"🔄 Skill cache reloaded. **{len(inventory)}** skills active.",
                ephemeral=True,
            )
            return

        if action == "list":
            inventory = get_skill_inventory()
            if not inventory:
                await interaction.response.send_message(
                    "📭 No skills loaded. The Tower has much to learn.",
                    ephemeral=True,
                )
                return

            # Group by category
            by_cat: dict = {}
            for s in inventory:
                cat = s["category"]
                by_cat.setdefault(cat, []).append(s)

            embed = discord.Embed(
                title="🧠 Tower Skill Library",
                description=f"**{len(inventory)}** skills loaded",
                color=discord.Color.blue(),
            )

            cat_emojis = {
                "lore": "📜",
                "systems": "⚙️",
                "rules": "📖",
                "persona": "🎭",
                "style": "🎨",
                "learned": "🤖",
                "unknown": "❓",
            }

            for cat, cat_skills in sorted(by_cat.items()):
                emoji = cat_emojis.get(cat, "📄")
                lines = []
                for s in cat_skills:
                    src_tag = " 🤖" if s["source"] == "self-learned" else ""
                    lines.append(f"`{s['filename']}` — {s['title']} (v{s['version']}){src_tag}")
                embed.add_field(
                    name=f"{emoji} {cat.title()} ({len(cat_skills)})",
                    value="\n".join(lines[:10]),  # cap at 10 per category
                    inline=False,
                )

            embed.set_footer(text="Use /skills action:View skill_name:<filename> to inspect a skill")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action == "view":
            if not skill_name:
                await interaction.response.send_message(
                    "❌ Please provide a `skill_name` (the filename, e.g. `undercity_lore.md`).",
                    ephemeral=True,
                )
                return

            # Normalize: add .md if missing
            if not skill_name.endswith(".md"):
                skill_name += ".md"

            body = get_skill_body(skill_name)
            if not body:
                await interaction.response.send_message(
                    f"❌ Skill `{skill_name}` not found. Use `/skills action:List` to see available skills.",
                    ephemeral=True,
                )
                return

            # Truncate for Discord embed (4096 char limit for description)
            if len(body) > 3900:
                body = body[:3900] + "\n\n*... truncated ...*"

            embed = discord.Embed(
                title=f"🧠 {skill_name}",
                description=f"```md\n{body}\n```",
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        elif action == "stats":
            inventory = get_skill_inventory()
            total = len(inventory)
            by_source = {}
            by_cat = {}
            for s in inventory:
                by_source[s["source"]] = by_source.get(s["source"], 0) + 1
                by_cat[s["category"]] = by_cat.get(s["category"], 0) + 1

            # Check journal for last learning session
            journal_path = SKILLS_DIR.parent.parent / "logs" / "journal.txt"
            last_session = "Never"
            if journal_path.exists():
                try:
                    lines = journal_path.read_text(encoding="utf-8").splitlines()
                    for line in reversed(lines):
                        if "LEARNING SESSION START" in line:
                            # Extract timestamp
                            ts_match = line.split("]")[0].lstrip("[")
                            last_session = ts_match
                            break
                except Exception:
                    pass

            embed = discord.Embed(
                title="📊 Skill System Stats",
                color=discord.Color.purple(),
            )
            embed.add_field(
                name="Total Skills",
                value=str(total),
                inline=True,
            )
            embed.add_field(
                name="By Source",
                value="\n".join(f"**{k}**: {v}" for k, v in sorted(by_source.items())),
                inline=True,
            )
            embed.add_field(
                name="By Category",
                value="\n".join(f"**{k}**: {v}" for k, v in sorted(by_cat.items())),
                inline=True,
            )
            embed.add_field(
                name="Last Learning Session",
                value=last_session,
                inline=False,
            )
            embed.add_field(
                name="Skills Directory",
                value=f"`{SKILLS_DIR}`",
                inline=False,
            )
            embed.set_footer(text="Self-learning runs daily between 1:00 AM – 2:00 AM")

            await interaction.response.send_message(embed=embed, ephemeral=True)
