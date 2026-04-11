"""Mission resolution & reaction handler — /resolvemission, on_raw_reaction_add."""

import os
import discord
from discord import app_commands

from src.log import logger
from src.mission_board import handle_reaction_claim, EMOJI_CLAIM, _get_results_channel


def setup(client):
    """Register mission commands on the client's command tree."""

    @client.tree.command(
        name="resolvemission",
        description="(DM only) Mark a claimed mission complete or failed by title search."
    )
    @app_commands.describe(
        title="Part of the mission title to search for",
        outcome="complete or fail"
    )
    @app_commands.choices(outcome=[
        app_commands.Choice(name="\u2705 Complete", value="complete"),
        app_commands.Choice(name="\U0001f4a5 Failed",   value="fail"),
    ])
    async def resolvemission(interaction: discord.Interaction, title: str, outcome: str):
        from src.mission_board import (
            _load_missions, _save_missions, _generate, _build_complete_prompt
        )
        from src.faction_reputation import on_mission_complete, on_mission_failed, format_rep_change

        dm_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_id:
            await interaction.response.send_message("\u274c DM only.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        missions = _load_missions()
        matches  = [
            (i, m) for i, m in enumerate(missions)
            if title.lower() in m.get("title", "").lower()
            and not m.get("completed") and not m.get("failed")
        ]

        if not matches:
            await interaction.followup.send(
                f"\u274c No active unresolved mission found matching **'{title}'**.",
                ephemeral=True
            )
            return

        if len(matches) > 1:
            names = "\n".join(f"- {m['title']}" for _, m in matches)
            await interaction.followup.send(
                f"\u274c Multiple matches \u2014 be more specific:\n{names}",
                ephemeral=True
            )
            return

        idx, mission = matches[0]
        claimer = mission.get("player_claimer", "Unknown Adventurer")
        faction = mission.get("faction", "")

        # Delete old claim post from the mission board
        board_channel_id = int(os.getenv("MISSION_BOARD_CHANNEL_ID", 0))
        board_channel = client.get_channel(board_channel_id)
        if board_channel:
            claim_msg_id = mission.get("claim_message_id")
            if claim_msg_id:
                try:
                    old = await board_channel.fetch_message(claim_msg_id)
                    await old.delete()
                except Exception:
                    pass

        # Results channel for posting outcome notices
        results_channel = await _get_results_channel(client, fallback_channel=board_channel)

        if outcome == "complete":
            prompt = _build_complete_prompt(mission, claimer)
            notice = await _generate(prompt)
            if not notice:
                notice = f"\U0001f3c6 **CONTRACT COMPLETE \u2014 {mission['title']}**\n*{claimer} has returned. The contract is fulfilled.*"
            mission["completed"] = True
            rep_result = on_mission_complete(faction) if faction else None
        else:
            fail_prompt = f"""You are the Undercity mission board posting a failure notice.
Mission: {mission.get('title', 'Unknown')}
Faction: {faction}
Tier: {mission.get('tier', 'standard')}
Attempted by: {claimer}
Format:
\U0001f4a5 **CONTRACT FAILED \u2014 {mission.get('title', 'Unknown')}**
*{claimer} did not complete the job. [1-2 sentences: what went wrong.]*
RULES: Gritty, terse. No preamble, no sign-off."""
            notice = await _generate(fail_prompt)
            if not notice:
                notice = f"\U0001f4a5 **CONTRACT FAILED \u2014 {mission['title']}**\n*{claimer} did not complete the job. The faction is not pleased.*"
            mission["failed"] = True
            rep_result = on_mission_failed(faction) if faction else None

        mission["resolved"] = True
        _save_missions(missions)

        if results_channel:
            await results_channel.send(notice)

        rep_line = f"\n{format_rep_change(rep_result)}" if rep_result else ""
        await interaction.followup.send(
            f"{'✅' if outcome == 'complete' else '💥'} **{mission['title']}** marked as **{outcome}**."
            f"{rep_line}",
            ephemeral=True
        )

    # --- Reaction handler for mission claims ---

    @client.event
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
        """Handle ⚔️ (player claim) reactions on mission board posts."""
        logger.info(f"⚔️ RAW REACTION RECEIVED: emoji={payload.emoji}, channel={payload.channel_id}, user={payload.user_id}")
        
        if payload.user_id == client.user.id:
            logger.debug("⚔️ Ignoring bot's own reaction")
            return

        mission_channel_id = int(os.getenv("MISSION_BOARD_CHANNEL_ID", 0))
        logger.info(f"⚔️ Channel check: payload.channel_id={payload.channel_id}, mission_channel_id={mission_channel_id}")
        if payload.channel_id != mission_channel_id:
            logger.debug(f"⚔️ Wrong channel, ignoring")
            return

        # Strip variation selector U+FE0F — Discord sometimes drops it from returned payloads
        _emoji_str = str(payload.emoji).replace('\ufe0f', '')
        _claim_str = EMOJI_CLAIM.replace('\ufe0f', '')
        logger.info(f"⚔️ Emoji check: '{_emoji_str}' vs EMOJI_CLAIM '{_claim_str}'")
        if _emoji_str != _claim_str:
            logger.debug(f"⚔️ Wrong emoji, ignoring")
            return

        channel = client.get_channel(payload.channel_id)
        if channel is None:
            logger.warning(f"⚔️ Channel {payload.channel_id} not found in cache")
            return
        try:
            message = await channel.fetch_message(payload.message_id)
            user    = await client.fetch_user(payload.user_id)
            logger.info(f"⚔️ Fetched message and user, calling handle_reaction_claim")
        except Exception as e:
            logger.error(f"⚔️ Failed to fetch message/user: {e}")
            return

        reaction = type("R", (), {"message": message, "emoji": payload.emoji})()
        dm_id = int(os.getenv("DM_USER_ID", 0))
        logger.info(f"⚔️ Calling handle_reaction_claim for user {user.display_name}")
        await handle_reaction_claim(reaction, user, dm_id, client=client)
        logger.info(f"⚔️ handle_reaction_claim completed")

    # Log that the event handler was registered
    logger.info(f"⚔️ on_raw_reaction_add event handler registered for mission claims")
