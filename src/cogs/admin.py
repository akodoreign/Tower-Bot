"""Admin, settings, and utility commands — /sync, /provider, /switchpersona,
/private, /replyall, /help, /towerbay, /myauctions, /newsdraft, /patches."""

import os
import re
from pathlib import Path
import discord
from discord import app_commands

from src.log import logger
from src.providers import ProviderType
from src import personas
from src.player_listings import _TowerBayModal, format_player_listings_embed


# ---------------------------------------------------------------------------
# Patch approval system
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PATCHES_FILE = PROJECT_ROOT / "skills" / "module-quality" / "PATCHES.md"


def _parse_pending_patches() -> list:
    """
    Parse PATCHES.md and return list of pending patches.
    
    Each patch dict has: id, timestamp, mission, score, content, status
    """
    if not PATCHES_FILE.exists():
        return []
    
    try:
        text = PATCHES_FILE.read_text(encoding="utf-8")
    except Exception:
        return []
    
    patches = []
    
    # Find patch sections: "## Patches from YYYY-MM-DD HH:MM"
    sections = re.split(r"\n---\n", text)
    
    for section in sections:
        if "## Patches from" not in section:
            continue
        
        # Extract header info
        header_match = re.search(r"## Patches from (\d{4}-\d{2}-\d{2} \d{2}:\d{2})", section)
        mission_match = re.search(r"\*\*Test Mission:\*\*\s*(.+)", section)
        score_match = re.search(r"\*\*Quality Score:\*\*\s*(\d+)/10", section)
        
        timestamp = header_match.group(1) if header_match else "Unknown"
        mission = mission_match.group(1).strip() if mission_match else "Unknown"
        score = score_match.group(1) if score_match else "?"
        
        # Find individual patches: "### Patch N"
        patch_blocks = re.split(r"### Patch \d+", section)
        
        for i, block in enumerate(patch_blocks[1:], 1):  # Skip first (header)
            # Extract content between ``` markers
            content_match = re.search(r"```\n?(.+?)\n?```", block, re.DOTALL)
            status_match = re.search(r"\*\*Status:\*\*\s*(⏳|✅|❌|�\udd04)\s*(\w+)", block)
            
            content = content_match.group(1).strip() if content_match else block.strip()[:500]
            status = status_match.group(2) if status_match else "PENDING"
            
            if status == "PENDING":
                patch_id = f"{timestamp.replace(' ', '_').replace(':', '')}_{i}"
                patches.append({
                    "id": patch_id,
                    "timestamp": timestamp,
                    "mission": mission,
                    "score": score,
                    "content": content,
                    "status": status,
                    "index": i,
                })
    
    return patches


def _update_patch_status(patch_id: str, new_status: str) -> bool:
    """
    Update a patch's status in PATCHES.md.
    
    Args:
        patch_id: Patch identifier (timestamp_index)
        new_status: New status ("✅ APPROVED", "❌ REJECTED", "�\udd04 MODIFIED")
    
    Returns:
        True if updated, False if not found
    """
    if not PATCHES_FILE.exists():
        return False
    
    try:
        text = PATCHES_FILE.read_text(encoding="utf-8")
    except Exception:
        return False
    
    # Parse patch_id to get timestamp and index
    parts = patch_id.rsplit("_", 1)
    if len(parts) != 2:
        return False
    
    ts_part, idx_str = parts
    # Reconstruct timestamp format: "YYYY-MM-DD_HHMM" -> "YYYY-MM-DD HH:MM"
    ts_formatted = ts_part[:10] + " " + ts_part[11:13] + ":" + ts_part[13:15]
    patch_idx = int(idx_str)
    
    # Find the section with this timestamp
    pattern = rf"(## Patches from {re.escape(ts_formatted)}.*?### Patch {patch_idx}.*?\*\*Status:\*\*\s*)⏳ PENDING"
    
    new_text = re.sub(
        pattern,
        rf"\g<1>{new_status}",
        text,
        flags=re.DOTALL,
    )
    
    if new_text == text:
        return False
    
    try:
        PATCHES_FILE.write_text(new_text, encoding="utf-8")
        return True
    except Exception:
        return False


class _PatchApprovalView(discord.ui.View):
    """DM view for reviewing a prompt patch."""

    def __init__(self, patch: dict, all_patches: list, current_index: int):
        super().__init__(timeout=600)  # 10 minute timeout
        self.patch = patch
        self.all_patches = all_patches
        self.current_index = current_index

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        success = _update_patch_status(self.patch["id"], "✅ APPROVED")
        if success:
            await interaction.response.edit_message(
                content=f"✅ **Patch APPROVED:** `{self.patch['id']}`\n\nApply this to prompts in:\n"
                        f"- `src/agents/learning_agents.py` (ProAuthorAgent)\n"
                        f"- `src/mission_compiler.py` (section system prompt)\n"
                        f"- `skills/module-quality/SKILL.md`",
                view=None,
            )
        else:
            await interaction.response.edit_message(
                content="❌ Failed to update patch status.", view=None
            )
        # Send next patch if available
        await self._send_next_patch(interaction)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        success = _update_patch_status(self.patch["id"], "❌ REJECTED")
        if success:
            await interaction.response.edit_message(
                content=f"❌ **Patch REJECTED:** `{self.patch['id']}`",
                view=None,
            )
        else:
            await interaction.response.edit_message(
                content="❌ Failed to update patch status.", view=None
            )
        await self._send_next_patch(interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.grey, emoji="⏭️")
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content=f"⏭️ **Skipped patch:** `{self.patch['id']}` (still pending)",
            view=None,
        )
        await self._send_next_patch(interaction)

    async def _send_next_patch(self, interaction: discord.Interaction):
        """Send the next pending patch if available."""
        # Refresh patch list
        patches = _parse_pending_patches()
        if not patches:
            await interaction.followup.send(
                "🎉 **All patches reviewed!** No more pending patches.",
                ephemeral=True,
            )
            return
        
        # Send first remaining patch
        patch = patches[0]
        embed = _build_patch_embed(patch, 1, len(patches))
        view = _PatchApprovalView(patch, patches, 0)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


def _build_patch_embed(patch: dict, current: int, total: int) -> discord.Embed:
    """Build an embed for displaying a patch."""
    embed = discord.Embed(
        title=f"�\udcdd Patch Review ({current}/{total})",
        color=discord.Color.blue(),
    )
    embed.add_field(
        name="Source",
        value=f"**Mission:** {patch['mission']}\n"
              f"**Score:** {patch['score']}/10\n"
              f"**Generated:** {patch['timestamp']}",
        inline=False,
    )
    
    # Truncate content if too long
    content = patch["content"]
    if len(content) > 900:
        content = content[:900] + "\n... [truncated]"
    
    embed.add_field(
        name="Proposed Prompt Addition",
        value=f"```\n{content}\n```",
        inline=False,
    )
    embed.set_footer(text=f"Patch ID: {patch['id']}")
    
    return embed


# ---------------------------------------------------------------------------
# Draft bulletin approval view
# ---------------------------------------------------------------------------

class _BulletinApprovalView(discord.ui.View):
    """Ephemeral DM view for reviewing a draft bulletin before posting."""

    def __init__(self, formatted: str, raw: str, channel_id: int):
        super().__init__(timeout=300)
        self.formatted  = formatted
        self.raw        = raw
        self.channel_id = channel_id

    @discord.ui.button(label="Post it", style=discord.ButtonStyle.green, emoji="✅")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        from src.news_feed import _write_memory
        _write_memory(self.raw)
        channel = interaction.client.get_channel(self.channel_id)
        if channel:
            await channel.send(self.formatted)
            await interaction.response.edit_message(
                content="✅ **Posted to channel.**", view=None
            )
        else:
            await interaction.response.edit_message(
                content="❌ Could not find channel to post to.", view=None
            )

    @discord.ui.button(label="Discard", style=discord.ButtonStyle.red, emoji="❌")
    async def discard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(
            content="❌ **Bulletin discarded.**", view=None
        )

    @discord.ui.button(label="Regenerate", style=discord.ButtonStyle.grey, emoji="🔄")
    async def regenerate(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        from src.news_feed import generate_bulletin_draft
        formatted, raw = await generate_bulletin_draft()
        if not formatted:
            await interaction.followup.send("❌ Regeneration failed.", ephemeral=True)
            return
        self.formatted = formatted
        self.raw       = raw
        new_view = _BulletinApprovalView(formatted, raw, self.channel_id)
        await interaction.edit_original_response(
            content=f"**📝 Draft bulletin for review:**\n\n{formatted}",
            view=new_view,
        )


def setup(client):
    """Register admin/utility commands on the client's command tree."""

    # ---- /sync ----

    @client.tree.command(
        name="sync",
        description="(Admin) Force-sync slash commands in this server",
    )
    async def sync_commands(interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "\u274c You don't have permission to sync commands.",
                ephemeral=True,
            )
            return
        try:
            await client.tree.sync(guild=interaction.guild)
            await interaction.response.send_message(
                "\u2705 Commands synced! Try `/setcharprofile` again.", ephemeral=True
            )
            logger.info(
                f"\u2705 Manual command sync triggered by {interaction.user} in guild {interaction.guild.name}"
            )
        except Exception as e:
            logger.error(f"\u274c Manual command sync failed: {e}")
            await interaction.response.send_message(
                f"\u274c Sync failed: {e}", ephemeral=True
            )

    # ---- /provider ----

    @client.tree.command(name="provider", description="Switch AI provider")
    async def provider(interaction: discord.Interaction):
        class ProviderSelect(discord.ui.Select):
            def __init__(self):
                options = []
                available = client.provider_manager.get_available_providers()
                emoji_map = {ProviderType.FREE: "\U0001f193"}
                for p in available:
                    options.append(
                        discord.SelectOption(
                            label=p.value.capitalize(),
                            value=p.value,
                            emoji=emoji_map.get(p, "\U0001f916"),
                        )
                    )
                super().__init__(placeholder="Select provider", options=options)

            async def callback(self, interaction: discord.Interaction):
                provider_type = ProviderType(self.values[0])
                client.switch_provider(provider_type)
                await interaction.response.send_message(
                    f"\u2705 Provider set to **{provider_type.value}**",
                    ephemeral=True,
                )

        view = discord.ui.View()
        view.add_item(ProviderSelect())

        info = client.get_current_provider_info()
        embed = discord.Embed(
            title="AI Provider Settings",
            description=f"**Current Provider:** {info['provider']}\n"
                        f"**Model:** {info['current_model']}",
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    # ---- /switchpersona ----

    @client.tree.command(name="switchpersona", description="Switch AI persona")
    async def switchpersona(interaction: discord.Interaction, persona: str):
        user_id = str(interaction.user.id)
        available = personas.get_available_personas(user_id)
        if persona not in available:
            await interaction.response.send_message(
                f"\u274c Invalid persona. Available: {', '.join(available)}",
                ephemeral=True,
            )
            return
        await client.switch_persona(persona, user_id)
        await interaction.response.send_message(
            f"\U0001f3ad Persona switched to **{persona}**",
            ephemeral=False,
        )

    # ---- /private, /replyall ----

    @client.tree.command(name="private", description="Toggle private replies")
    async def private(interaction: discord.Interaction):
        client.isPrivate = not client.isPrivate
        await interaction.response.send_message(
            f"\U0001f527 Private mode: {client.isPrivate}", ephemeral=False,
        )

    @client.tree.command(name="replyall", description="Toggle replyAll")
    async def replyall(interaction: discord.Interaction):
        client.is_replying_all = not client.is_replying_all
        await interaction.response.send_message(
            f"\U0001f527 replyAll mode: {client.is_replying_all}", ephemeral=False,
        )

    # ---- /help ----

    @client.tree.command(name="help", description="Show all commands")
    async def help_cmd(interaction: discord.Interaction):
        embed = discord.Embed(
            title="\U0001f916 Tower Bot Commands",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Chat",
            value="`/chat` \u2014 Talk to the Tower\n`/reset` \u2014 Reset conversation",
            inline=False,
        )
        embed.add_field(
            name="Character",
            value="`/setcharprofile` \u2014 Set character\n`/showcharprofile` \u2014 View character",
            inline=False,
        )
        embed.add_field(
            name="Admin",
            value="`/sync` \u2014 Sync slash commands",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    # ---- /towerbay, /myauctions ----

    @client.tree.command(
        name="towerbay",
        description="List an item from your character sheet on TowerBay for auction.",
    )
    async def towerbay_command(interaction: discord.Interaction):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if not dm_user_id:
            await interaction.response.send_message(
                "\u274c TowerBay submissions are disabled \u2014 DM_USER_ID not configured.",
                ephemeral=True,
            )
            return
        modal = _TowerBayModal(dm_user_id=dm_user_id)
        await interaction.response.send_modal(modal)

    @client.tree.command(
        name="myauctions",
        description="Check the current status of all active TowerBay player listings.",
    )
    async def myauctions_command(interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        embed = format_player_listings_embed()
        if embed is None:
            await interaction.followup.send(
                "\U0001f3ea No active player listings on TowerBay right now. Use `/towerbay` to list an item!",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(embed=embed)

    # ---- /newsdraft (DM only) ----

    @client.tree.command(
        name="newsdraft",
        description="[DM only] Generate a bulletin draft for review before posting.",
    )
    async def newsdraft_command(interaction: discord.Interaction):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        channel_id_str = os.getenv("DISCORD_CHANNEL_ID", "")
        if not channel_id_str:
            await interaction.response.send_message(
                "\u274c DISCORD_CHANNEL_ID not set — can't determine target channel.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        from src.news_feed import generate_bulletin_draft
        formatted, raw = await generate_bulletin_draft()

        if not formatted:
            await interaction.followup.send(
                "\u274c Draft generation failed — Ollama may be offline.", ephemeral=True
            )
            return

        view = _BulletinApprovalView(formatted, raw, int(channel_id_str))
        await interaction.followup.send(
            f"**\U0001f4dd Draft bulletin for review:**\n\n{formatted}",
            view=view,
            ephemeral=True,
        )

    # -----------------------------------------------------------------
    # /archive — full weekly archiver
    # -----------------------------------------------------------------

    @client.tree.command(
        name="archive",
        description="[DM only] Archive resolved missions, sold items, old news, and more."
    )
    async def archive_cmd(interaction: discord.Interaction):
        dm_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from src.weekly_archive import run_weekly_archive, archive_summary

        results = run_weekly_archive()
        summary = archive_summary()

        lines = ["**\U0001f4e6 Archive Results:**"]
        labels = {
            "missions":        "\u2694\ufe0f Missions",
            "towerbay":        "\U0001f3ea TowerBay",
            "player_listings": "\U0001f4b0 Player listings",
            "bounties":        "\U0001f3af Bounties",
            "missing_persons": "\U0001f50d Missing persons",
            "outcomes":        "\U0001f4cb Outcomes",
            "graveyard":       "\U0001f480 Graveyard",
            "news_snapshot":   "\U0001f4f0 News snapshot",
        }
        for key, label in labels.items():
            val = results.get(key, 0)
            if isinstance(val, bool):
                lines.append(f"{label}: {'saved' if val else 'nothing new'}")
            elif val > 0:
                lines.append(f"{label}: **{val}** archived")
            else:
                lines.append(f"{label}: nothing to archive")

        lines.append("")
        lines.append("**\U0001f4ca Archive Inventory:**")
        for cat, info in summary.items():
            lines.append(f"  {cat}: {info['weeks']} weeks, {info['records']} records")

        await interaction.followup.send("\n".join(lines), ephemeral=True)

    # -----------------------------------------------------------------
    # /riftlist — show active rifts
    # -----------------------------------------------------------------

    @client.tree.command(
        name="riftlist",
        description="[DM only] Show all active Rift events and their current stage."
    )
    async def riftlist_cmd(interaction: discord.Interaction):
        dm_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        from src.news_feed import _load_rift_state
        rifts = _load_rift_state()
        active = [r for r in rifts if not r.get("resolved")]
        resolved = [r for r in rifts if r.get("resolved")]

        if not active and not resolved:
            await interaction.response.send_message(
                "\U0001f30a No rifts in the system.", ephemeral=True
            )
            return

        lines = []
        if active:
            lines.append("**\U0001f30a Active Rifts:**")
            for r in active:
                stage = r.get("stage", "?")
                loc   = r.get("location", "?")
                rid   = r.get("id", "?")
                spawned = r.get("spawned_at", "")[:10]
                stage_emoji = {"whisper": "\U0001f444", "tremor": "\U0001f4a2",
                               "crack": "\u26a0\ufe0f", "open": "\U0001f6a8",
                               "critical": "\u2622\ufe0f"}.get(stage, "\u2753")
                lines.append(f"{stage_emoji} **{stage.upper()}** \u2014 {loc}")
                lines.append(f"   ID: `{rid}` \u00b7 Spawned: {spawned}")
        else:
            lines.append("**\U0001f30a No active rifts.**")

        if resolved:
            recent = sorted(resolved, key=lambda r: r.get("sealed_at", r.get("spawned_at", "")), reverse=True)[:5]
            lines.append("")
            lines.append("**Recent resolved:**")
            for r in recent:
                outcome = r.get("outcome", "?")
                loc = r.get("location", "?")
                emoji = "\u2705" if outcome == "sealed" else "\U0001f4a5"
                lines.append(f"{emoji} {loc} \u2014 {outcome}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # -----------------------------------------------------------------
    # /sealrift — manually seal a rift (player completed mission, etc)
    # -----------------------------------------------------------------

    @client.tree.command(
        name="sealrift",
        description="[DM only] Manually seal an active Rift (e.g. players completed a rift mission)."
    )
    @app_commands.describe(
        rift_id="Rift ID from /riftlist (e.g. 'rift_1742307600')",
        sealed_by="Who sealed it — player party name, NPC, or faction",
    )
    async def sealrift_cmd(
        interaction: discord.Interaction,
        rift_id: str,
        sealed_by: str = "player party",
    ):
        dm_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from src.news_feed import _load_rift_state, _save_rift_state, _generate_rift_bulletin, _write_memory
        from datetime import datetime as _dt

        rifts = _load_rift_state()
        target = None
        for r in rifts:
            if r.get("id") == rift_id and not r.get("resolved"):
                target = r
                break

        if not target:
            await interaction.followup.send(
                f"\u274c No active rift found with ID `{rift_id}`. Use `/riftlist` to see active rifts.",
                ephemeral=True,
            )
            return

        stage = target.get("stage", "?")
        loc   = target.get("location", "?")

        target["resolved"]  = True
        target["outcome"]   = "sealed"
        target["sealed_by"] = sealed_by
        target["sealed_at"] = _dt.now().isoformat()
        target["seal_desc"] = f"Sealed by {sealed_by} at the {stage} stage near {loc}."
        _save_rift_state(rifts)

        # Generate and post a sealing bulletin
        channel_id_str = os.getenv("DISCORD_CHANNEL_ID", "")
        channel = client.get_channel(int(channel_id_str)) if channel_id_str else None

        bulletin = await _generate_rift_bulletin(target, "sealed")
        if bulletin and channel:
            _write_memory(bulletin)
            from src.news_feed import _dual_timestamp
            formatted = f"-# \U0001f570\ufe0f {_dual_timestamp()}\n{bulletin}"
            await channel.send(formatted)

        await interaction.followup.send(
            f"\u2705 Rift **{rift_id}** at **{loc}** ({stage} stage) sealed by **{sealed_by}**.\n"
            f"{'Bulletin posted to channel.' if bulletin and channel else 'No bulletin generated.'}",
            ephemeral=True,
        )
