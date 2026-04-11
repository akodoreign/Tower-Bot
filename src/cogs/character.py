"""Character profile & appearance commands — /setcharprofile, /showcharprofile,
/setcharappearance, /showcharappearance."""

import os
import discord
from discord import app_commands

from src.log import logger
from src.character_profiles import (
    has_character_profile,
    load_character_profile,
    save_character_profile,
    load_character_appearance,
    save_character_appearance,
)


def setup(client):
    """Register character commands on the client's command tree."""

    @client.tree.command(
        name="setcharprofile", description="Tell the Tower who your character is."
    )
    @app_commands.describe(
        profile="e.g. Name: Dusk | Class: Warlock 5 | Role: Face | Notes: Squishy blaster"
    )
    async def setcharprofile(interaction: discord.Interaction, profile: str):
        user_id = interaction.user.id
        save_character_profile(user_id, profile)
        await interaction.response.send_message(
            "\U0001f4d8 The Tower nods. *I will remember who you are.*",
            ephemeral=True,
        )

    @client.tree.command(
        name="showcharprofile", description="Show what the Tower remembers about you."
    )
    async def showcharprofile(interaction: discord.Interaction):
        user_id = interaction.user.id
        profile = load_character_profile(user_id)

        if not profile:
            await interaction.response.send_message(
                "\u274c No character profile found.\nCreate one with `/setcharprofile`.\n\n"
                "**Example:**\n"
                "`/setcharprofile profile: Name: Brynn | Class: Fighter 5 | Role: Tank | "
                "Notes: Punch-first philosophy`",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"\U0001f4d8 **Your Character Profile:**\n```{profile}```",
            ephemeral=True,
        )

    # ---- Character Appearance ----

    @client.tree.command(
        name="setcharappearance",
        description="(DM) Upload a reference image for a player character — llava will describe their appearance."
    )
    @app_commands.describe(
        player="The player whose character this image is for",
        character_name="The character's in-game name (e.g. Eleanor Reed)",
        image="Reference image of the character (art, token, photo, etc.)"
    )
    async def setcharappearance(
        interaction: discord.Interaction,
        player: discord.Member,
        image: discord.Attachment,
        character_name: str = "",
    ):
        import httpx, base64

        dm_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_id:
            await interaction.response.send_message("\u274c DM only.", ephemeral=True)
            return

        if not image.content_type or not image.content_type.startswith("image/"):
            await interaction.response.send_message("\u274c Please attach an image file.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        # Download the image and base64 encode it for llava
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                img_resp = await http.get(image.url)
                img_resp.raise_for_status()
                img_b64 = base64.b64encode(img_resp.content).decode("utf-8")
        except Exception as e:
            await interaction.followup.send(f"\u274c Failed to download image: {e}", ephemeral=True)
            return

        profile = load_character_profile(player.id) or "No profile set."

        # Look up confirmed species from player_characters DB table
        confirmed_species = ""
        if character_name:
            from src.mission_board import _load_characters, CHARACTER_MEMORY_FILE
            for char in _load_characters():
                if char.get("NAME", "").lower() == character_name.lower():
                    confirmed_species = char.get("SPECIES", "").strip()
                    current_player = char.get("PLAYER", "").strip()
                    new_player = player.name
                    if current_player != new_player:
                        # Update player_name in DB (primary)
                        try:
                            from src.db_api import raw_execute as _rx
                            _rx(
                                "UPDATE player_characters SET player_name=%s, updated_at=NOW() WHERE LOWER(name)=LOWER(%s)",
                                (new_player, character_name)
                            )
                            logger.info(f"player_characters DB: PLAYER for {character_name}: {current_player!r} -> {new_player!r}")
                        except Exception as _e:
                            logger.warning(f"Could not update player_name in DB for {character_name}: {_e}")
                        # Write-through to file
                        try:
                            import re as _re
                            if CHARACTER_MEMORY_FILE.exists():
                                raw = CHARACTER_MEMORY_FILE.read_text(encoding="utf-8")
                                blocks = raw.split("---CHARACTER---")
                                for bi, block in enumerate(blocks):
                                    if _re.search(rf'^NAME:\s*{_re.escape(character_name)}\s*$', block,
                                                  _re.MULTILINE | _re.IGNORECASE):
                                        blocks[bi] = _re.sub(
                                            r'^(PLAYER:\s*)\S+',
                                            lambda pm: pm.group(1) + new_player,
                                            block, count=1, flags=_re.MULTILINE
                                        )
                                        break
                                updated = "---CHARACTER---".join(blocks)
                                if updated != raw:
                                    CHARACTER_MEMORY_FILE.write_text(updated, encoding="utf-8")
                        except Exception as _e:
                            logger.warning(f"Could not update PLAYER field in file for {character_name}: {_e}")
                    break

        # Build species constraint line for the prompt
        if confirmed_species:
            species_line = (
                f"IMPORTANT: This character is confirmed to be a {confirmed_species}. "
                f"You MUST describe them as {confirmed_species}. "
                f"Do NOT describe them as any other species or race.\n\n"
            )
        elif character_name:
            species_line = (
                f"This character's name is {character_name}. "
                f"Describe their species/race from what you can observe in the image.\n\n"
            )
        else:
            species_line = ""

        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
        prompt_text = (
            f"This is a reference image for a tabletop RPG character. "
            f"{species_line}"
            f"Their profile: {profile}\n\n"
            "Describe this character's physical appearance in 2-3 sentences suitable for use "
            "as a Stable Diffusion prompt insert. Focus on: race/species, build, hair, eyes, "
            "skin tone, notable features, and clothing/armour style. "
            "Be specific and visual. No story, no personality, no names. Just appearance."
        )

        try:
            async with httpx.AsyncClient(timeout=120.0) as http:
                resp = await http.post(ollama_url, json={
                    "model": "llava",
                    "messages": [{"role": "user", "content": prompt_text, "images": [img_b64]}],
                    "stream": False,
                })
                resp.raise_for_status()
                data = resp.json()

            appearance = data.get("message", {}).get("content", "").strip()
        except Exception as e:
            await interaction.followup.send(f"\u274c llava failed: {e}", ephemeral=True)
            return

        if not appearance:
            await interaction.followup.send("\u274c llava returned an empty description. Try a clearer image.", ephemeral=True)
            return

        save_character_appearance(player.id, appearance, character_name=character_name)

        name_line = f" as **{character_name}**" if character_name else ""
        await interaction.followup.send(
            f"\u2705 Appearance saved for **{player.display_name}**{name_line}:\n```{appearance}```",
            ephemeral=True
        )

    @client.tree.command(
        name="showcharappearance",
        description="Show the saved appearance description for your character."
    )
    async def showcharappearance(interaction: discord.Interaction):
        from src.character_profiles import load_character_name
        appearance = load_character_appearance(interaction.user.id)
        if not appearance:
            await interaction.response.send_message(
                "\u274c No appearance saved yet. Ask your DM to use `/setcharappearance`.",
                ephemeral=True
            )
            return
        char_name = load_character_name(interaction.user.id)
        header = f"\U0001f3a8 **{char_name}** \u2014 appearance:" if char_name else "\U0001f3a8 **Your character appearance:**"
        await interaction.response.send_message(
            f"{header}\n```{appearance}```",
            ephemeral=True
        )
