"""Image generation commands — /draw, /drawscene, /gearrun."""

import os
import random
import asyncio
import discord
from discord import app_commands

from src.log import logger
from src.npc_lookup import get_npc_sd_prompt, extract_and_lookup_npcs


def setup(client):
    """Register image generation commands on the client's command tree."""

    @client.tree.command(
        name="draw",
        description="Generate a dark fantasy image. Describe a scene, person, or place in the Undercity."
    )
    @app_commands.describe(
        prompt="What to render \u2014 e.g. 'a hooded tiefling in a rain-soaked alley, lanterns gleaming'",
        orientation="Wide cinematic (default) or tall portrait"
    )
    @app_commands.choices(orientation=[
        app_commands.Choice(name="Wide (default)", value="wide"),
        app_commands.Choice(name="Portrait",       value="portrait"),
    ])
    async def draw(
        interaction: discord.Interaction,
        prompt: str,
        orientation: str = "wide",
    ):
        import httpx, base64, io

        allowed_channels = {1479466957714624757, 1479458224280305835}
        if interaction.channel_id not in allowed_channels:
            await interaction.response.send_message(
                "\u274c `/draw` can only be used in the designated image channels.",
                ephemeral=True
            )
            return

        if len(prompt) > 600:
            await interaction.response.send_message("\u274c Prompt too long (max 600 chars).", ephemeral=True)
            return

        await interaction.response.defer()

        a1111_url = os.getenv("A1111_URL", "http://127.0.0.1:7860")
        model     = os.getenv("A1111_MODEL", "")
        width, height = (896, 512) if orientation == "wide" else (512, 896)

        # Check for quoted NPC names and inject their appearance
        npc_appearance = get_npc_sd_prompt(prompt)
        npc_matches = extract_and_lookup_npcs(prompt)
        if npc_matches:
            npc_names = [m['name'] for m in npc_matches]
            logger.info(f"🎨 /draw detected NPCs: {npc_names}")
        
        # Build full prompt with NPC appearance injected
        base_prompt = prompt.rstrip(",. ")
        if npc_appearance:
            base_prompt = f"{base_prompt}, {npc_appearance}"
            logger.info(f"🎨 /draw injected NPC appearance: {npc_appearance[:80]}...")
        
        full_prompt = (
            base_prompt
            + ", photorealistic, cinematic lighting, highly detailed, 8k, sharp focus, atmospheric"
        )
        negative = (
            "text, watermark, signature, blurry, low quality, ugly, deformed, "
            "cartoon, anime, painting, illustration, drawing, sketch"
        )

        payload = {
            "prompt":          full_prompt,
            "negative_prompt": negative,
            "steps":           50,
            "cfg_scale":       7.5,
            "width":           width,
            "height":          height,
            "sampler_name":    "Euler a",
            "batch_size":      1,
            "seed":            random.randint(1, 999999),
            "restore_faces":   False,
            "tiling":          False,
        }

        if model:
            try:
                async with httpx.AsyncClient(timeout=30.0) as http:
                    opts = (await http.get(f"{a1111_url}/sdapi/v1/options")).json()
                if opts.get("sd_model_checkpoint", "") != model:
                    async with httpx.AsyncClient(timeout=30.0) as http:
                        await http.post(f"{a1111_url}/sdapi/v1/options", json={"sd_model_checkpoint": model})
            except Exception:
                pass

        from src.news_feed import a1111_lock, _a1111_lock
        from src.image_ref import (
            get_best_ref_for_scene, to_img2img_payload,
            detect_and_save_refs,
        )

        if _a1111_lock.locked():
            await interaction.followup.send(
                "\u23f3 A1111 is currently generating another image. Please try again in about 5 minutes.",
                ephemeral=True
            )
            return

        # Check for reference images to use as img2img base
        ref_bytes, denoise, ref_source = get_best_ref_for_scene(prompt)
        if ref_bytes:
            api_payload = to_img2img_payload(payload, ref_bytes, denoise)
            endpoint = f"{a1111_url}/sdapi/v1/img2img"
            logger.info(f"\U0001f3a8 /draw using img2img ref: {ref_source} (denoise={denoise})")
        else:
            api_payload = payload
            endpoint = f"{a1111_url}/sdapi/v1/txt2img"

        async with a1111_lock:
            try:
                async with httpx.AsyncClient(timeout=600.0) as http:
                    resp = await http.post(endpoint, json=api_payload)
                    resp.raise_for_status()
                    data = resp.json()

                img_bytes = base64.b64decode(data["images"][0])

                # Auto-save as reference for detected NPCs/locations
                detect_and_save_refs(prompt, img_bytes)

                file = discord.File(io.BytesIO(img_bytes), filename="undercity.png")

                embed = discord.Embed(
                    title="\U0001f3a8 Undercity Vision",
                    color=discord.Color.dark_grey(),
                )
                if ref_source:
                    embed.set_footer(text=f"\U0001f504 Built on ref: {ref_source}")
                embed.set_image(url="attachment://undercity.png")

                await interaction.followup.send(embed=embed, file=file)

            except Exception as e:
                import traceback
                logger.error(f"draw command error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
                await interaction.followup.send(
                    f"\u274c Image generation failed \u2014 is A1111 running? (`{type(e).__name__}: {e}`)",
                    ephemeral=True
                )

    # ---- /drawscene (DM only) ----

    @client.tree.command(
        name="drawscene",
        description="[DM only] Generate a story image from a specific scene description.",
    )
    @app_commands.describe(
        scene="Scene description, e.g. 'Sera Voss and Corvin Thale argue in a dim alley'",
    )
    async def drawscene_command(interaction: discord.Interaction, scene: str):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "❌ This command is restricted to the DM.", ephemeral=True
            )
            return

        channel_id_str = os.getenv("DISCORD_CHANNEL_ID", "")
        if not channel_id_str:
            await interaction.response.send_message(
                "❌ DISCORD_CHANNEL_ID not set.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        import httpx as _httpx
        from src.news_feed import (
            a1111_lock, _AESTHETIC_FALLBACK,
            _get_district_aesthetic, _extract_scene_action,
        )
        from src.npc_appearance import find_npc_in_text
        import base64 as _base64

        A1111_URL = os.getenv("A1111_URL", "http://127.0.0.1:7860")
        image_style = os.getenv("IMAGE_STYLE", "photorealistic").lower().strip()
        is_anime    = image_style == "anime"
        if is_anime:
            A1111_MODEL = os.getenv("A1111_ANIME_MODEL", os.getenv("A1111_MODEL", "sd_epicrealismXL_pureFix"))
        else:
            A1111_MODEL = os.getenv("A1111_MODEL", "sd_epicrealismXL_pureFix")

        district_aesthetic = _get_district_aesthetic(scene)
        if district_aesthetic is _AESTHETIC_FALLBACK:
            district_aesthetic = _AESTHETIC_FALLBACK
        scene_action = _extract_scene_action(scene)

        found_npcs = find_npc_in_text(scene)
        char_parts = []
        for npc_name, npc_sd, _ in found_npcs[:4]:
            if npc_sd:
                char_parts.append(npc_sd.split('.')[0].strip())

        if is_anime:
            quality_header = (
                "masterpiece, best quality, very aesthetic, absurdres"
            )
            char_block = ", ".join(char_parts) if char_parts else "2characters"
            _LOC_TAG_MAP = {
                "neon row":           "neon lights, underground street, crowded alleyway",
                "cobbleway market":   "market stall, underground street, neon signs",
                "floating bazaar":    "underground lake, lanterns reflecting on water, floating platform",
                "crimson alley":      "neon lights, dark alley, steam, red lighting",
                "taste of worlds":    "food stall, lanterns, underground market",
                "markets infinite":   "underground city, neon signs, brutalist pillars, crowd",
                "grand forum":        "greek columns, marble floor, holographic display, underground civic hall",
                "central plaza":      "stone plaza, fountain, underground city, neon signage",
                "grand forum library":"library, arched ceiling, bookshelves, amber lighting",
                "adventurer's inn":   "tavern, stone walls, low lighting, rough tables",
                "guild spires":       "brutalist tower, glass facade, underground city skyline",
                "arena of ascendance":"fighting arena, stadium lighting, tiered seating, sand floor",
                "sanctum quarter":    "ancient temple, stone columns, candles, incense smoke",
                "pantheon walk":      "stone colonnade, shrine alcoves, candlelight",
                "shantytown heights": "slum, corrugated tin walls, hanging laundry, narrow path",
                "scrapworks":         "industrial salvage yard, welding sparks, metal scrap piles",
                "night pits":         "underground fight pit, neon signs, dark concrete, spotlight",
                "echo alley":         "dark alley, graffiti walls, bioluminescent moss",
                "collapsed plaza":    "rubble, cave, dim green light, abandoned space",
                "outer wall":         "brutalist concrete wall, floodlights, military checkpoint",
                "warrens":            "slum alley, graffiti, illegal wiring, bioluminescent fungus",
                "alley":              "dark alley, neon lights, wet pavement, underground city",
                "inn":                "tavern, stone walls, low lighting, rough tables",
            }
            scene_lower = scene.lower()
            loc_tags = "underground city, dark fantasy setting, neon lights"
            for key, tags in _LOC_TAG_MAP.items():
                if key in scene_lower:
                    loc_tags = tags
                    break
            framing = "cowboy shot, 2characters, dynamic pose, characters in foreground, environment background, dramatic lighting, volumetric lighting, lens flare, dynamic shadow, english text, latin alphabet"
            image_prompt = ", ".join([quality_header, char_block, scene_action, loc_tags, framing])
            negative_prompt = (
                "nsfw, lowres, (bad), text overlay, watermark, logo, copyright, "
                "error, fewer, extra, missing, "
                "worst quality, jpeg artifacts, low quality, unfinished, "
                "displeasing, oldest, early, chromatic aberration, "
                "signature, username, scan, (abstract), "
                "chinese text, japanese text, korean text, arabic text, "
                "cyrillic text, foreign script, illegible text, "
                "flat color, simple background, retro anime, 80s anime, "
                "chibi, super deformed, sketch, lineart only, "
                "portrait, face close-up, headshot, cropped, close up, "
                "photorealistic, 3d render, western cartoon"
            )
        else:
            parts = ["wide establishing shot, multiple figures visible in mid-ground"]
            parts.append(district_aesthetic)
            parts.append(scene_action)
            if char_parts:
                parts.append(", ".join(char_parts))
            parts.append(
                "camera far back, environment fills majority of frame, "
                "characters in mid-ground, brutalist concrete and neon atmosphere"
            )
            image_prompt = ", ".join(parts)
            image_prompt += (
                ", RAW photo, wide angle lens, 24mm, f/5.6, "
                "environmental wide shot, cinematic lighting, highly detailed, sharp focus, 8k"
            )
            negative_prompt = (
                "text, watermark, signature, blurry, low quality, ugly, deformed, "
                "cartoon, anime, painting, illustration, drawing, sketch, "
                "cgi, render, 3d, plastic, oversaturated, game screenshot, "
                "portrait, close-up, headshot, face only, cropped, "
                "medieval castle, stone dungeon, fantasy castle interior, torch sconces"
            )

        try:
            async with _httpx.AsyncClient(timeout=30.0) as http:
                r = await http.get(f"{A1111_URL}/sdapi/v1/options")
                current = r.json().get("sd_model_checkpoint", "")
                if A1111_MODEL not in current:
                    await http.post(f"{A1111_URL}/sdapi/v1/options", json={"sd_model_checkpoint": A1111_MODEL})
        except Exception as _me:
            await interaction.followup.send(f"❌ A1111 not reachable: {_me}", ephemeral=True)
            return

        payload = {
            "prompt": image_prompt,
            "negative_prompt": negative_prompt,
            "steps": 40, "cfg_scale": 5.0,
            "width": 896, "height": 512,
            "sampler_name": "Euler a",
            "batch_size": 1, "n_iter": 1,
            "seed": random.randint(1, 999999),
            "restore_faces": False, "tiling": False,
        }

        # Check for reference images to use as img2img base
        from src.image_ref import (
            get_best_ref_for_scene, to_img2img_payload,
            detect_and_save_refs, SCENE_DENOISE,
        )
        ref_bytes, denoise, ref_source = get_best_ref_for_scene(scene)
        if ref_bytes:
            api_payload = to_img2img_payload(payload, ref_bytes, denoise)
            endpoint = f"{A1111_URL}/sdapi/v1/img2img"
            ref_note = f" (img2img ref: {ref_source})"
            logger.info(f"\U0001f3a8 /drawscene using img2img ref: {ref_source} (denoise={denoise})")
        else:
            api_payload = payload
            endpoint = f"{A1111_URL}/sdapi/v1/txt2img"
            ref_note = ""

        await interaction.followup.send(
            f"⏳ Generating scene image...{ref_note} (this takes ~30-60s)", ephemeral=True
        )

        async with a1111_lock:
            try:
                async with _httpx.AsyncClient(timeout=900.0) as http:
                    r = await http.post(endpoint, json=api_payload)
                    r.raise_for_status()
                    result = r.json()
                img_bytes = _base64.b64decode(result["images"][0])
                try:
                    from PIL import Image as _PILImage
                    import io as _io2
                    _img = _PILImage.open(_io2.BytesIO(img_bytes))
                    _w, _h = _img.size
                    _img = _img.crop((0, 0, _w, _h - 52))
                    _buf = _io2.BytesIO()
                    _img.save(_buf, format="PNG")
                    img_bytes = _buf.getvalue()
                except Exception:
                    pass
            except Exception as _ge:
                await interaction.followup.send(f"❌ Generation failed: {_ge}", ephemeral=True)
                return

        # Auto-save as reference for detected NPCs/locations
        detect_and_save_refs(scene, img_bytes)

        channel = client.get_channel(int(channel_id_str))
        if channel:
            caption = f"*{scene}*"
            await channel.send(
                content=caption,
                file=discord.File(fp=__import__('io').BytesIO(img_bytes), filename="scene.png"),
            )
            await interaction.followup.send("✅ Scene posted to channel.", ephemeral=True)
        else:
            await interaction.followup.send("❌ Couldn't find the channel.", ephemeral=True)

    # ---- /gearrun (DM only) ----

    @client.tree.command(
        name="gearrun",
        description="[DM only] Generate NPC appearance profiles for all roster NPCs.",
    )
    async def gearrun_command(interaction: discord.Interaction):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from src.npc_appearance import NPC_ROSTER_FILE, _profile_path, generate_all_npc_appearances
        from src.party_profiles import PARTY_PROFILE_DIR, load_profile
        from src.mission_board import _load_party_list, USED_PARTIES_FILE
        import json as _json

        if NPC_ROSTER_FILE.exists():
            roster = _json.loads(NPC_ROSTER_FILE.read_text(encoding="utf-8"))
        else:
            roster = []
        npc_total   = len(roster)
        npc_already = sum(1 for n in roster if _profile_path(n.get("name", "")).exists())
        npc_pending = npc_total - npc_already

        party_names = set(_load_party_list())
        if USED_PARTIES_FILE.exists():
            try:
                party_names.update(_json.loads(USED_PARTIES_FILE.read_text(encoding="utf-8")))
            except Exception:
                pass
        for f in PARTY_PROFILE_DIR.glob("*.json"):
            try:
                d = _json.loads(f.read_text(encoding="utf-8"))
                if "name" in d:
                    party_names.add(d["name"])
            except Exception:
                pass
        party_total   = len(party_names)
        party_already = sum(1 for n in party_names if (lambda p: p is not None and p.get("generated"))(load_profile(n)))
        party_pending = party_total - party_already

        await interaction.followup.send(
            f"\u2699\ufe0f **Gear run starting.**\n"
            f"NPCs: **{npc_total}** total \u00b7 {npc_already} already done \u00b7 **{npc_pending} to generate**\n"
            f"Parties: **{party_total}** total \u00b7 {party_already} already done \u00b7 **{party_pending} to generate**\n"
            f"Runs in background (~2s per NPC via Ollama). I'll DM you when it's done.",
            ephemeral=True,
        )

        async def _run():
            try:
                results = await generate_all_npc_appearances(force=False)
                done    = len(results)
                try:
                    from src.party_profiles import generate_all_party_profiles
                    party_results = await generate_all_party_profiles(force=False)
                    p_done  = party_results.get('done', 0)
                    p_total = party_results.get('total', 0)
                except Exception as _pe:
                    p_done = p_total = 0
                    logger.warning(f"\U0001f3c5 Party gear run error: {_pe}")
                try:
                    dm_user = await client.fetch_user(dm_user_id)
                    p_skipped = party_results.get('skipped', 0) if p_total else 0
                    p_failed  = party_results.get('failed', 0)  if p_total else 0
                    party_line = (
                        f"\n\U0001f396\ufe0f Party profiles: **{p_done}** generated, "
                        f"{p_skipped} skipped, {p_failed} failed ({p_total} total)."
                    ) if p_total else ""
                    await dm_user.send(
                        f"\u2705 **Gear run complete.**\n"
                        f"NPC appearances: **{done}** generated/verified.{party_line}\n"
                        f"Story images and news bulletins will now reference real party members."
                    )
                except Exception:
                    pass
                logger.info(f"\U0001f3a8 Gear run complete: {done} NPC profiles, {p_done} party profiles")
            except Exception as e:
                logger.error(f"\U0001f3a8 Gear run error: {e}")
                try:
                    dm_user = await client.fetch_user(dm_user_id)
                    await dm_user.send(f"\u274c Gear run failed: {e}")
                except Exception:
                    pass

        asyncio.get_event_loop().create_task(_run())

    # ---- /pin (DM only) — pin last generated image as canonical reference ----

    @client.tree.command(
        name="pin",
        description="[DM only] Pin the last generated image as canonical ref for an NPC or location.",
    )
    @app_commands.describe(
        category="What to pin — NPC portrait or location scene",
        name="NPC name or location key (e.g. 'Serrik Dhal' or 'markets_infinite')",
    )
    @app_commands.choices(category=[
        app_commands.Choice(name="NPC",      value="npc"),
        app_commands.Choice(name="Location", value="location"),
    ])
    async def pin_command(
        interaction: discord.Interaction,
        category: str,
        name: str,
    ):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from src.image_ref import (
            pin_npc_ref, pin_location_ref,
            get_npc_ref, get_location_ref,
            has_npc_ref, has_location_ref,
        )

        # Strategy: look for the most recent image attachment in the channel
        # (the last /draw or /drawscene output)
        img_bytes = None
        try:
            async for msg in interaction.channel.history(limit=20):
                if msg.attachments:
                    for att in msg.attachments:
                        if att.filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
                            img_bytes = await att.read()
                            break
                if msg.embeds:
                    for embed in msg.embeds:
                        if embed.image and embed.image.url:
                            import httpx
                            async with httpx.AsyncClient(timeout=30.0) as http:
                                r = await http.get(embed.image.url)
                                if r.status_code == 200:
                                    img_bytes = r.content
                                    break
                if img_bytes:
                    break
        except Exception as e:
            await interaction.followup.send(f"\u274c Could not find a recent image: {e}", ephemeral=True)
            return

        if not img_bytes:
            await interaction.followup.send(
                "\u274c No recent image found in the last 20 messages. "
                "Use `/draw` or `/drawscene` first, then `/pin`.",
                ephemeral=True,
            )
            return

        if category == "npc":
            pin_npc_ref(name, img_bytes)
            await interaction.followup.send(
                f"\U0001f4cc **Pinned** canonical NPC reference for **{name}** "
                f"({len(img_bytes):,} bytes). Future `/draw` and `/drawscene` "
                f"commands will use this as the img2img base.",
                ephemeral=True,
            )
        else:
            pin_location_ref(name, img_bytes)
            await interaction.followup.send(
                f"\U0001f4cc **Pinned** canonical location reference for **{name}** "
                f"({len(img_bytes):,} bytes). Future scene generations in this "
                f"location will use this as the img2img base.",
                ephemeral=True,
            )

    # ---- /refstats (DM only) — show reference image inventory ----

    @client.tree.command(
        name="refstats",
        description="[DM only] Show how many reference images are stored for NPCs and locations.",
    )
    async def refstats_command(interaction: discord.Interaction):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        from src.image_ref import get_ref_stats, NPC_REFS, LOC_REFS

        stats = get_ref_stats()
        npc_details = []
        for d in sorted(NPC_REFS.iterdir()):
            if d.is_dir():
                pinned = "\U0001f4cc" if (d / "pinned.png").exists() else "  "
                refs = sum(1 for i in range(1, 4) if (d / f"ref_{i:03d}.png").exists())
                npc_details.append(f"{pinned} {d.name} ({refs} refs)")

        loc_details = []
        for d in sorted(LOC_REFS.iterdir()):
            if d.is_dir():
                pinned = "\U0001f4cc" if (d / "pinned.png").exists() else "  "
                refs = sum(1 for i in range(1, 4) if (d / f"ref_{i:03d}.png").exists())
                loc_details.append(f"{pinned} {d.name} ({refs} refs)")

        npc_list = "\n".join(npc_details[:25]) if npc_details else "*None yet*"
        loc_list = "\n".join(loc_details[:15]) if loc_details else "*None yet*"

        embed = discord.Embed(
            title="\U0001f5bc\ufe0f Image Reference Stats",
            color=discord.Color.dark_grey(),
        )
        embed.add_field(
            name=f"NPCs ({stats['npc_refs']} total, {stats['npc_pinned']} pinned)",
            value=f"```\n{npc_list}\n```",
            inline=False,
        )
        embed.add_field(
            name=f"Locations ({stats['location_refs']} total, {stats['location_pinned']} pinned)",
            value=f"```\n{loc_list}\n```",
            inline=False,
        )
        embed.set_footer(
            text="\U0001f4cc = pinned canonical ref. Use /pin to lock a good generation."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
