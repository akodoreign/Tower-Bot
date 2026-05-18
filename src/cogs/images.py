"""Image generation commands — /draw, /drawscene, /gearrun."""

import os
import re
import random
import asyncio
import discord
from discord import app_commands

from src.log import logger
from src.npc_lookup import get_npc_sd_prompt, extract_and_lookup_npcs


def setup(client):
    """Register image generation commands on the client's command tree."""

    # Maps a choice value → (checkpoint_name, is_anime, is_furry)
    # is_furry = True  → e621/Pony tag vocabulary, NSFW-capable, characters always foreground
    _DRAW_MODELS = {
        "juggernaut":  ("Juggernaut-XL_v9_RunDiffusionPhoto_v2", False, False),
        "epicrealism": ("epicrealismXL_pureFix",                  False, False),
        "aurelium":    ("aureliumPhotorealistic_v10",              False, False),
        "realvis":     ("RealVisXL_V4.0",                          False, False),
        "animagine":   ("animagineXLV31_v31",                      True,  False),
        "wail":        ("wailIlustriousSDXL_v160",                 True,  False),
        "realismillu": ("realismIllustriousBy_v50FP16",            False, False),
        "plantmilk":   ("plantMilkModelSuite_walnut",              False, False),
        "pony":        ("oneFORALLPlusUltra_v3DPOPony",            True,  True),
        "nova":        ("novaFurryXL_iIV160",                      True,  True),
    }

    @client.tree.command(
        name="draw",
        description="Generate a dark fantasy image. Describe a scene, person, or place in the Undercity."
    )
    @app_commands.describe(
        prompt="What to render — e.g. 'Sera Voss and Corvin argue in the Crimson Alley market at dusk'",
        orientation="Wide cinematic (default) or tall portrait",
        model="Which model to use (default: Juggernaut XL v9)",
        raw="Skip AI enrichment and send your prompt directly to Stable Diffusion",
    )
    @app_commands.choices(
        orientation=[
            app_commands.Choice(name="Wide (default)", value="wide"),
            app_commands.Choice(name="Portrait",       value="portrait"),
        ],
        model=[
            app_commands.Choice(name="Juggernaut XL v9 · cinematic photo (default)", value="juggernaut"),
            app_commands.Choice(name="epicrealism XL · gritty realistic",             value="epicrealism"),
            app_commands.Choice(name="Aurelium Photorealistic v10",                   value="aurelium"),
            app_commands.Choice(name="RealVis XL v4 · photorealistic",                value="realvis"),
            app_commands.Choice(name="AnimagineXL 3.1 · anime",                       value="animagine"),
            app_commands.Choice(name="Wail Illustrious SDXL · semi-anime",            value="wail"),
            app_commands.Choice(name="Realism Illustrious v50 · semi-real",           value="realismillu"),
            app_commands.Choice(name="Plant Milk Walnut · general",                   value="plantmilk"),
            app_commands.Choice(name="oneFORALL Ultra v3 · pony/NSFW",               value="pony"),
            app_commands.Choice(name="Nova Furry XL · furry/NSFW",                   value="nova"),
        ],
    )
    async def draw(
        interaction: discord.Interaction,
        prompt: str,
        orientation: str = "wide",
        model: str = "juggernaut",
        raw: bool = False,
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

        a1111_url    = os.getenv("A1111_URL", "http://127.0.0.1:7860")
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")

        # Resolve model checkpoint and flags from the dropdown selection
        checkpoint, is_anime, is_furry = _DRAW_MODELS.get(
            model,
            (os.getenv("A1111_MODEL", "Juggernaut-XL_v9_RunDiffusionPhoto_v2"), False, False)
        )
        model = checkpoint
        from src.resource_cop import wait_for_a1111_turn

        decision = await wait_for_a1111_turn(
            "draw_command",
            model_hint=model,
            max_wait_seconds=30,
        )
        if not decision.run_now:
            await interaction.followup.send(
                "\u23f3 A1111 is busy with another image job. Please try again in a minute.",
                ephemeral=True,
            )
            return

        width, height = (896, 512) if orientation == "wide" else (512, 896)

        # Detect NPC names and pull their appearance descriptors from DB
        npc_matches    = extract_and_lookup_npcs(prompt)
        npc_names      = [m["name"] for m in npc_matches] if npc_matches else []
        npc_appearance = get_npc_sd_prompt(prompt)
        if npc_names:
            logger.info(f"🎨 /draw detected NPCs: {npc_names}")

        full_prompt = prompt.rstrip(",. ")

        if raw:
            # Raw mode: user controls everything, just append NPC appearance tags
            if npc_appearance:
                full_prompt = f"{full_prompt}, {npc_appearance}"
            full_prompt += ", photorealistic, cinematic lighting, highly detailed, 8k, sharp focus"
            logger.info("🎨 /draw raw mode — skipping AI enrichment")
        else:
            # Enriched mode: run through qwen to build a grounded, environment-first SD prompt
            from src.news_feed import _get_district_aesthetic
            district = _get_district_aesthetic(prompt)

            if is_furry:
                # e621/Pony tag vocabulary — characters always foreground, NSFW enabled
                sys_prompt = (
                    "You are an expert Stable Diffusion prompt engineer for furry/anthro models "
                    "(Nova Furry XL, Pony Diffusion). These models use e621-style tags.\n\n"
                    "OUTPUT FORMAT: comma-separated e621 tags on ONE line. No prose.\n\n"
                    "TAG ORDER:\n"
                    "1. RATING — explicit, mature, or questionable\n"
                    "2. SPECIES — anthro [species], e.g. anthro wolf, anthro fox, anthro dragon\n"
                    "3. CHARACTER DETAILS — body type, fur colour, markings, features\n"
                    "4. ACTION / POSE — what they are doing, position, expression\n"
                    "5. SCENE — location, lighting, background\n\n"
                    "For Pony Diffusion add: score_9, score_8_up, score_7_up at the start.\n"
                    "10–25 tags total. Characters are always the primary subject — foreground, detailed, clear."
                )
                pony_prefix = "score_9, score_8_up, score_7_up, " if "pony" in checkpoint.lower() else ""
                user_msg = (
                    f"Scene request: {prompt}\n"
                    f"Output ONLY the e621 tags. Start with: {pony_prefix}explicit (or mature/questionable as appropriate)."
                )
            elif is_anime:
                sys_prompt = (
                    "You are an expert Stable Diffusion XL prompt engineer for AnimagineXL 3.1.\n"
                    "Output ONLY comma-separated Danbooru tags — no prose, no sentences.\n"
                    "Order: character tags → action/pose tags → location tags.\n"
                    "10–20 tags total on ONE line. No quality or framing tags."
                )
                char_hint = (
                    f"Characters: {', '.join(npc_names)}" if npc_names
                    else "unnamed figures"
                )
                user_msg = (
                    f"Scene: {prompt}\n"
                    f"{char_hint}\n"
                    f"Location aesthetic: {district}\n"
                    f"Output ONLY the comma-separated Danbooru tags."
                )
            else:
                sys_prompt = (
                    "You are an expert Stable Diffusion XL prompt engineer for photorealistic models "
                    "(Juggernaut XL v9, epiCRealism). These models understand natural English short "
                    "phrases, NOT Danbooru tags.\n\n"
                    "Your goal: write a prompt where the LOCATION and STORY are the primary subject. "
                    "Characters appear as secondary figures in the midground — NOT the focus.\n\n"
                    "OUTPUT FORMAT: comma-separated short English phrases on ONE line.\n\n"
                    "STRICT ORDERING:\n"
                    "1. LOCATION — specific place, architecture, surfaces, spatial depth\n"
                    "2. ATMOSPHERE — lighting, time of day, colour palette, air quality\n"
                    "3. STORY ACTION — what event is happening (crowd reacting, fire burning, etc.)\n"
                    "4. CHARACTERS LAST — one brief phrase only: 'two figures in the distance', "
                    "'silhouetted figure in a doorway'. No face details. No close-up appearance.\n\n"
                    "12–20 phrases total on ONE line. No quality or framing tags."
                )
                char_hint = (
                    f"Characters (show as distant/secondary): {', '.join(npc_names)}"
                    if npc_names else "no named characters — use an anonymous crowd or lone figure"
                )
                user_msg = (
                    f"User scene request: {prompt}\n"
                    f"{char_hint}\n"
                    f"Location aesthetic: {district}\n\n"
                    f"Output ONLY the comma-separated phrases in order: "
                    f"location → atmosphere → story action → characters last."
                )

            enriched = ""
            try:
                from src.ollama_queue import call_ollama, OllamaBusyError
                data = await call_ollama(
                    payload={
                        "model": ollama_model,
                        "messages": [
                            {"role": "system", "content": sys_prompt},
                            {"role": "user",   "content": user_msg},
                        ],
                        "stream": False,
                        "options": {"num_predict": 256, "num_ctx": 16384, "think": True},
                    },
                    timeout=45.0,
                    caller="draw_enrich",
                )
                raw_out = ""
                if isinstance(data, dict):
                    msg = data.get("message", {})
                    if isinstance(msg, dict):
                        raw_out = msg.get("content", "").strip()

                import re as _re
                # Strip qwen3 thinking blocks and markdown fences
                raw_out = _re.sub(r"<think>.*?</think>", "", raw_out, flags=_re.DOTALL).strip()
                raw_out = _re.sub(r"```[a-z]*\n?", "", raw_out).replace("```", "").strip()

                # Pick the line with the most commas — survives preamble and trailing explanations
                all_lines = [l.strip() for l in raw_out.splitlines() if l.strip()]
                tag_lines = [l for l in all_lines if l.count(",") >= 3]
                if tag_lines:
                    raw_out = max(tag_lines, key=lambda l: l.count(","))
                elif all_lines:
                    raw_out = " ".join(all_lines).strip()

                if raw_out.count(",") >= 4:
                    enriched = raw_out
                    logger.info(f"🎨 /draw qwen enriched prompt ({raw_out.count(',') + 1} phrases)")
                else:
                    logger.warning(f"🎨 /draw qwen short output — using user prompt (sample: {raw_out[:80]!r})")

            except Exception as _qe:
                logger.warning(f"🎨 /draw qwen unavailable ({_qe}) — using user prompt directly")

            if enriched:
                full_prompt = enriched
            else:
                # Fallback: inject NPC appearance and add style suffix
                if npc_appearance:
                    full_prompt = f"{full_prompt}, {npc_appearance}"

            # Style suffix (quality/framing tags added after qwen output)
            if is_furry:
                if "pony" not in checkpoint.lower():
                    full_prompt += ", masterpiece, best quality, detailed fur, highly detailed, sharp focus"
                # Pony already has score tags prepended — no suffix needed
            elif is_anime:
                full_prompt += ", masterpiece, best quality, very aesthetic, absurdres"
            else:
                full_prompt += (
                    ", RAW photo, wide angle lens, 24mm, f/5.6, "
                    "environmental wide shot, cinematic lighting, highly detailed, sharp focus, 8k"
                )

        if is_furry:
            negative = (
                "human, human only, realistic photo, photograph, "
                "text, watermark, signature, blurry, low quality, "
                "poorly drawn, bad anatomy, bad hands, extra limbs, deformed, ugly, "
                "bad proportions, malformed"
            )
        elif is_anime:
            negative = (
                "nsfw, text, watermark, signature, blurry, low quality, "
                "bad anatomy, bad hands, extra limbs, deformed, ugly, "
                "realistic photo, photograph, 3d render"
            )
        else:
            negative = (
                "text, watermark, signature, blurry, low quality, ugly, deformed, "
                "cartoon, anime, painting, illustration, drawing, sketch, "
                "cgi, render, 3d, plastic, oversaturated, "
                "portrait, close-up, headshot, face only, cropped, "
                "shallow depth of field, bokeh, subject isolation"
            )

        if is_furry:
            steps, cfg = 30, 7.0
            sampler = "DPM++ 2M Karras"
        elif is_anime:
            steps, cfg = 28, 7.0
            sampler = "DPM++ 2M SDE Karras"
        else:
            steps, cfg = 45, 5.0
            sampler = "DPM++ 2M SDE Karras"

        payload = {
            "prompt":          full_prompt,
            "negative_prompt": negative,
            "steps":           steps,
            "cfg_scale":       cfg,
            "width":           width,
            "height":          height,
            "sampler_name":    sampler,
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

        from src.news_feed import a1111_lock
        from src.image_ref import (
            get_best_ref_for_scene, to_img2img_payload,
        )

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
        layered="Two-pass render: environment first, then characters composited in (~2x time)",
    )
    async def drawscene_command(interaction: discord.Interaction, scene: str, layered: bool = False):
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
            A1111_MODEL = os.getenv("A1111_ANIME_MODEL", os.getenv("A1111_MODEL", "Juggernaut-XL_v9_RunDiffusionPhoto_v2"))
        else:
            A1111_MODEL = os.getenv("A1111_MODEL", "Juggernaut-XL_v9_RunDiffusionPhoto_v2")
        from src.resource_cop import wait_for_a1111_turn

        decision = await wait_for_a1111_turn(
            "drawscene_command",
            model_hint=A1111_MODEL,
            max_wait_seconds=30,
        )
        if not decision.run_now:
            await interaction.followup.send(
                "\u23f3 A1111 is busy with another image job. Please try again in a minute.",
                ephemeral=True,
            )
            return

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
                "shallow depth of field, bokeh, subject isolation, "
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
            "steps": 45, "cfg_scale": 5.0,
            "width": 896, "height": 512,
            "sampler_name": "DPM++ 2M SDE Karras",
            "batch_size": 1, "n_iter": 1,
            "seed": random.randint(1, 999999),
            "restore_faces": False, "tiling": False,
        }

        from src.image_ref import (
            get_best_ref_for_scene, to_img2img_payload,
            layered_generate,
        )

        if layered:
            # Build background-only prompt (no characters)
            if is_anime:
                bg_prompt = f"{quality_header}, {loc_tags}, {district_aesthetic}, wide establishing shot, empty scene, no people, no characters"
            else:
                bg_prompt = (
                    f"{loc_tags}, {district_aesthetic}, "
                    "wide establishing shot, empty plaza, no people, no characters, "
                    "RAW photo, wide angle lens, 24mm, f/5.6, cinematic lighting, highly detailed, sharp focus, 8k"
                )
            await interaction.followup.send(
                "⏳ Layered render: pass 1 environment, pass 2 characters (~90-120s)", ephemeral=True
            )
            async with a1111_lock:
                try:
                    img_bytes, bg_bytes = await layered_generate(
                        background_prompt=bg_prompt,
                        full_prompt=image_prompt,
                        negative_prompt=negative_prompt,
                        payload_base=payload,
                        a1111_url=A1111_URL,
                        char_denoise=0.60,
                    )
                except Exception as _ge:
                    await interaction.followup.send(f"❌ Layered generation failed: {_ge}", ephemeral=True)
                    return
        else:
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
                except Exception as _ge:
                    await interaction.followup.send(f"❌ Generation failed: {_ge}", ephemeral=True)
                    return

        # Crop A1111 info bar from bottom
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

    gearrun_group = app_commands.Group(
        name="gearrun",
        description="[DM only] Mimir-backed NPC/PC gear population.",
    )

    @gearrun_group.command(
        name="standard",
        description="Fill missing NPC profiles, party profiles, and normal Mimir equipment.",
    )
    async def gearrun_standard_command(interaction: discord.Interaction):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from src.npc_appearance import generate_all_npc_appearances, get_npc_appearance
        from src.party_profiles import load_profile
        from src.mission_board import _load_party_list, _load_used_parties
        from src.db_api import raw_query as _rq
        import json as _json

        # Load NPC roster from DB — count against the same DB source generate_all uses
        _npc_rows = _rq("SELECT name FROM npcs WHERE status IN ('alive','injured','undead','doppelganger') ORDER BY name") or []
        roster = [{"name": r["name"]} for r in _npc_rows]
        npc_total   = len(roster)
        npc_already = sum(1 for n in roster if get_npc_appearance(n.get("name", "")) is not None)
        npc_pending = npc_total - npc_already

        # Load party names from DB
        party_names = set(_load_party_list())
        party_names.update(_load_used_parties())
        try:
            db_party_rows = _rq("SELECT party_name FROM party_profiles") or []
            for r in db_party_rows:
                if r.get("party_name"):
                    party_names.add(r["party_name"])
        except Exception:
            pass
        party_total   = len(party_names)
        party_already = sum(1 for n in party_names if (lambda p: p is not None and p.get("generated"))(load_profile(n)))
        party_pending = party_total - party_already

        await interaction.followup.send(
            f"\u2699\ufe0f **Standard gear run starting.**\n"
            f"NPCs: **{npc_total}** total \u00b7 {npc_already} already done \u00b7 **{npc_pending} to generate**\n"
            f"Parties: **{party_total}** total \u00b7 {party_already} already done \u00b7 **{party_pending} to generate**\n"
            f"PC Mimir gear: will fill only characters with no DDB/MySQL inventory.\n"
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
                npc_gear_stats = {"total": 0, "done": 0, "skipped": 0, "failed": 0}
                npc_synced = 0
                try:
                    from src.mimir_sync import run_npc_gear_run, get_sync_engine
                    npc_gear_stats = await run_npc_gear_run(force=False)
                    npc_synced = await get_sync_engine().sync_all_npcs()
                except Exception as _nge:
                    logger.warning(f"\U0001f6e1\ufe0f NPC Mimir gear run error: {_nge}")
                pc_stats = {"total": 0, "done": 0, "skipped": 0, "failed": 0}
                pc_synced = 0
                try:
                    from src.mimir_sync import run_pc_gear_run, get_sync_engine
                    pc_stats = await run_pc_gear_run(force=False)
                    pc_synced = await get_sync_engine().sync_party()
                except Exception as _pce:
                    logger.warning(f"\U0001f3d7\ufe0f PC Mimir gear run error: {_pce}")
                try:
                    dm_user = await client.fetch_user(dm_user_id)
                    p_skipped = party_results.get('skipped', 0) if p_total else 0
                    p_failed  = party_results.get('failed', 0)  if p_total else 0
                    party_line = (
                        f"\n\U0001f396\ufe0f Party profiles: **{p_done}** generated, "
                        f"{p_skipped} skipped, {p_failed} failed ({p_total} total)."
                    ) if p_total else ""
                    await dm_user.send(
                        f"\u2705 **Standard gear run complete.**\n"
                        f"NPC appearances: **{done}** generated/verified.{party_line}\n"
                        f"NPC Mimir gear: **{npc_gear_stats['done']}** filled, "
                        f"{npc_gear_stats['skipped']} skipped, {npc_gear_stats['failed']} failed "
                        f"({npc_gear_stats['total']} total). Synced: **{npc_synced}**.\n"
                        f"PC Mimir gear: **{pc_stats['done']}** filled, "
                        f"{pc_stats['skipped']} skipped, {pc_stats['failed']} failed "
                        f"({pc_stats['total']} total). Synced: **{pc_synced}**.\n"
                        f"Story images and news bulletins will now reference real party members."
                    )
                except Exception:
                    pass
                logger.info(
                    f"\U0001f3a8 Standard gear run complete: {done} NPC profiles, "
                    f"{p_done} party profiles, {npc_gear_stats['done']} NPC gear fills, "
                    f"{pc_stats['done']} PC gear fills"
                )
            except Exception as e:
                logger.error(f"\U0001f3a8 Standard gear run error: {e}")
                try:
                    dm_user = await client.fetch_user(dm_user_id)
                    await dm_user.send(f"\u274c Standard gear run failed: {e}")
                except Exception:
                    pass

        asyncio.get_event_loop().create_task(_run())

    @gearrun_group.command(
        name="epic",
        description="Apply real Mimir epic gear to NPCs over level 12.",
    )
    @app_commands.describe(
        min_level="Minimum NPC level to upgrade. Default: 13.",
        force="Replace mundane/lower-tier weapons and armor with epic versions.",
        npc_name="Optional exact NPC name, e.g. Captain Havel Korin.",
    )
    async def gearrun_epic_command(
        interaction: discord.Interaction,
        min_level: int = 13,
        force: bool = False,
        npc_name: str = "",
    ):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        min_level = max(13, min(int(min_level or 13), 20))
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            f"\u2694\ufe0f **Epic gear run starting.**\n"
            f"Target: `{npc_name or 'all living NPCs'}` | minimum level: **{min_level}** | force: **{force}**\n"
            f"Only Mimir catalog-confirmed items will be applied. I’ll DM you when it finishes.",
            ephemeral=True,
        )

        async def _run_epic():
            try:
                from src.mimir_client import get_mimir
                from src.mimir_sync import run_epic_npc_gear_run, get_sync_engine

                mimir = get_mimir()
                connected = mimir.available or await mimir.connect()
                if not connected:
                    raise RuntimeError("Mimir MCP unavailable; epic gear requires catalog validation.")

                stats = await run_epic_npc_gear_run(
                    min_level=min_level,
                    force=force,
                    npc_name=npc_name.strip(),
                )
                synced = await get_sync_engine().sync_all_npcs()
                updated = stats.get("updated") or []
                tail = "\n".join(f"- {line}" for line in updated[:12]) if updated else "- none"
                if len(updated) > 12:
                    tail += f"\n- ...and {len(updated) - 12} more"
                dm_user = await client.fetch_user(dm_user_id)
                await dm_user.send(
                    f"\u2705 **Epic gear run complete.**\n"
                    f"Eligible NPCs: **{stats.get('total', 0)}**\n"
                    f"Epic upgrades applied: **{stats.get('done', 0)}**\n"
                    f"Skipped: {stats.get('skipped', 0)} | Failed: {stats.get('failed', 0)} | "
                    f"Catalog misses: {stats.get('catalog_misses', 0)}\n"
                    f"Mimir characters synced: **{synced}**\n\n"
                    f"Updated:\n{tail}"
                )
            except Exception as e:
                logger.error(f"\u2694\ufe0f Epic gear run error: {e}")
                try:
                    dm_user = await client.fetch_user(dm_user_id)
                    await dm_user.send(f"\u274c Epic gear run failed: {e}")
                except Exception:
                    pass

        asyncio.get_event_loop().create_task(_run_epic())

    client.tree.add_command(gearrun_group)

    # ---- /generateareas (DM only) ----

    @client.tree.command(
        name="generateareas",
        description="[DM only] Generate living area profiles + maps for all Undercity districts.",
    )
    @app_commands.describe(
        district="Leave blank to run all districts. Specify one to regenerate just that district.",
        force="Re-generate even if a profile already exists (default: skip existing).",
    )
    async def generateareas_command(
        interaction: discord.Interaction,
        district: str = "",
        force: bool = False,
    ):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "❌ This command is restricted to the DM.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        from src.area_generator import (
            generate_area_profile,
            generate_all_area_profiles,
            get_all_district_names,
        )
        from src.db_api import raw_query as _rq

        if district.strip():
            # Single-district run
            known = [r["district"] for r in (_rq("SELECT DISTINCT district FROM gazetteer_places") or [])]
            if district not in known:
                await interaction.followup.send(
                    f"❌ Unknown district: **{district}**\n"
                    f"Known districts:\n" + "\n".join(f"  • {d}" for d in sorted(known)),
                    ephemeral=True,
                )
                return

            already = bool(_rq("SELECT id FROM area_profiles WHERE district=%s", (district,)))
            await interaction.followup.send(
                f"\U0001f5fa️ Generating area profile for **{district}**"
                + (" (force refresh)" if force else " — already exists, regenerating…" if already else "…"),
                ephemeral=True,
            )

            async def _run_one():
                try:
                    profile = await generate_area_profile(district, force=True)
                    try:
                        dm_user = await client.fetch_user(dm_user_id)
                        if profile:
                            atm = profile.get("atmosphere", "")[:200]
                            hooks = profile.get("dm_hooks", [])
                            hook_text = "\n".join(f"  • {h}" for h in hooks[:3])
                            await dm_user.send(
                                f"✅ **{district}** area profile complete.\n\n"
                                f"*{atm}*\n\n**DM Hooks:**\n{hook_text}\n\n"
                                f"Map + sub-locations stored in DB."
                            )
                        else:
                            await dm_user.send(f"❌ Area profile failed for **{district}**.")
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"generateareas single error: {e}")

            asyncio.get_event_loop().create_task(_run_one())
            return

        # Full run
        all_districts = [r["district"] for r in (_rq("SELECT DISTINCT district FROM gazetteer_places ORDER BY district") or [])]
        already_done  = len(get_all_district_names()) if not force else 0
        pending       = len(all_districts) - already_done if not force else len(all_districts)

        await interaction.followup.send(
            f"\U0001f5fa️ **Area generation starting.**\n"
            f"Districts: **{len(all_districts)}** total · {already_done} already done · **{pending} to generate**\n"
            f"Each district: LLM profile + ASCII grid map via A1111. Runs in background.\n"
            f"I'll DM you when complete.",
            ephemeral=True,
        )

        progress_log: list[str] = []

        async def _progress(dist, done, total, status="done"):
            icon = "✅" if status == "done" else "⏭️" if status == "skipped" else "❌"
            progress_log.append(f"{icon} {dist}")
            logger.info(f"[AreaGen] {icon} {dist} ({done}/{total})")

        async def _run_all():
            try:
                stats = await generate_all_area_profiles(force=force, progress_callback=_progress)
                try:
                    dm_user = await client.fetch_user(dm_user_id)
                    summary = "\n".join(progress_log[-10:])
                    if len(progress_log) > 10:
                        summary = f"…({len(progress_log)-10} more)…\n" + summary
                    await dm_user.send(
                        f"✅ **Area generation complete.**\n"
                        f"Generated: **{stats['done']}** · Skipped: {stats['skipped']} · Failed: {stats['failed']}\n\n"
                        f"**Last entries:**\n{summary}\n\n"
                        f"All profiles + maps stored in DB. Mission generator will now use them."
                    )
                except Exception:
                    pass
                logger.info(f"\U0001f5fa️ Area generation complete: {stats}")
            except Exception as e:
                logger.error(f"\U0001f5fa️ Area generation error: {e}")
                try:
                    dm_user = await client.fetch_user(dm_user_id)
                    await dm_user.send(f"❌ Area generation failed: {e}")
                except Exception:
                    pass

        asyncio.get_event_loop().create_task(_run_all())

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

    # ---- /backfill (DM only) — index historical Discord image embeds ----

    def _clean_backfill_title(title: str) -> tuple[str, bool]:
        text = re.sub(r"^[^\w'\"-]+", "", title or "").strip()
        is_alt = "alt universe" in text.lower()
        text = re.sub(r"\s+(?:[—–-]|\?)\s+Alt Universe\s*$", "", text, flags=re.IGNORECASE).strip()
        return text, is_alt

    def _strip_backfill_md(text: str) -> str:
        return re.sub(r"[*_`]", "", text or "").strip()

    def _parse_location_caption(description: str) -> tuple[str, str, str]:
        text = _strip_backfill_md(description)
        match = re.match(r"(.+?)\s+(?:[—–-]|\?)\s+([^|]+)(?:\|(.+))?$", text)
        if not match:
            return "", "", text
        return match.group(1).strip(), match.group(2).strip(), (match.group(3) or "").strip()

    def _canonical_npc_names() -> dict[str, str]:
        names: dict[str, str] = {}
        try:
            from src.db_api import raw_query
            rows = raw_query("SELECT name FROM npcs WHERE COALESCE(status, 'alive') <> 'dead'") or []
            for row in rows:
                name = (row.get("name") or "").strip()
                if name:
                    names[name.lower()] = name
        except Exception:
            pass
        try:
            from src.db_api import raw_query
            rows = raw_query("SELECT name FROM player_characters") or []
            for row in rows:
                name = (row.get("name") or "").strip()
                if name:
                    names[name.lower()] = name
        except Exception:
            pass
        return names

    async def _message_image_bytes(msg: discord.Message, embed: discord.Embed | None = None) -> bytes | None:
        for att in msg.attachments:
            if (att.filename or "").lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                return await att.read()
        if embed and embed.image and embed.image.url:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(embed.image.url) as resp:
                        if resp.status == 200:
                            return await resp.read()
            except Exception:
                return None
        return None

    @client.tree.command(
        name="backfill",
        description="[DM only] Backfill NPC/location image refs from historical Discord embeds.",
    )
    @app_commands.describe(
        target="Which historical embeds to backfill.",
        limit="How many recent messages to scan. Use 3000+ for older images.",
        dry_run="Preview matches without saving refs.",
        channel_id="Optional channel ID. Defaults to DISCORD_CHANNEL_ID.",
    )
    @app_commands.choices(target=[
        app_commands.Choice(name="NPC portraits", value="npcs"),
        app_commands.Choice(name="Location scenes", value="locations"),
        app_commands.Choice(name="Both", value="both"),
    ])
    async def backfill_command(
        interaction: discord.Interaction,
        target: str = "both",
        limit: int = 1000,
        dry_run: bool = True,
        channel_id: str = "",
    ):
        dm_user_id = int(os.getenv("DM_USER_ID", 0))
        if interaction.user.id != dm_user_id:
            await interaction.response.send_message(
                "\u274c This command is restricted to the DM.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        scan_limit = max(1, min(int(limit or 1000), 10000))
        try:
            default_channel_id = int(os.getenv("DISCORD_CHANNEL_ID") or interaction.channel_id)
            scan_channel_id = int(channel_id.strip()) if channel_id.strip() else default_channel_id
        except Exception:
            await interaction.followup.send("\u274c Invalid channel ID.", ephemeral=True)
            return

        channel = client.get_channel(scan_channel_id)
        if channel is None:
            try:
                channel = await client.fetch_channel(scan_channel_id)
            except Exception as e:
                await interaction.followup.send(f"\u274c Could not find channel `{scan_channel_id}`: {e}", ephemeral=True)
                return

        from src.image_ref import save_location_ref, save_npc_alt_ref, save_npc_ref

        canonical_npcs = _canonical_npc_names()
        matches = []
        scanned = skipped = name_skipped = 0
        async for msg in channel.history(limit=scan_limit):
            scanned += 1
            if not msg.embeds:
                continue
            for embed in msg.embeds:
                title = embed.title or ""
                footer = embed.footer.text if embed.footer else ""

                if target in ("npcs", "both"):
                    if "Undercity Roster" in footer or "What If" in footer or "Alt Universe" in title:
                        name, is_alt = _clean_backfill_title(title)
                        canonical_name = canonical_npcs.get(name.lower())
                        if not canonical_name:
                            name_skipped += 1
                            skipped += 1
                            continue
                        matches.append({
                            "kind": "npc_alt" if is_alt else "npc",
                            "name": canonical_name,
                            "district": "",
                            "message": msg,
                            "embed": embed,
                            "caption": title,
                        })
                        continue

                if target in ("locations", "both"):
                    if "The Undercity" in _strip_backfill_md(title):
                        place, district, detail = _parse_location_caption(embed.description or "")
                        if not place:
                            skipped += 1
                            continue
                        matches.append({
                            "kind": "location",
                            "name": place,
                            "district": district,
                            "message": msg,
                            "embed": embed,
                            "caption": embed.description or "",
                            "detail": detail,
                        })

        saved = failed = 0
        samples = []
        # Save oldest-to-newest so ref_001 remains the latest Discord image.
        for item in reversed(matches):
            msg = item["message"]
            img = await _message_image_bytes(msg, item.get("embed"))
            if not img:
                skipped += 1
                continue
            label = f"{item['kind']}:{item['name']}"
            if item.get("district"):
                label += f" ({item['district']})"
            samples.append(label)
            if dry_run:
                continue
            try:
                meta = {
                    "source": "discord_backfill_command",
                    "message_id": str(msg.id),
                    "channel_id": str(scan_channel_id),
                    "caption": item.get("caption", ""),
                    "created_at": msg.created_at.isoformat(),
                }
                if item["kind"] == "location":
                    meta["district"] = item.get("district", "")
                    meta["detail"] = item.get("detail", "")
                    save_location_ref(item["name"], img, metadata=meta)
                elif item["kind"] == "npc_alt":
                    meta["alt_universe"] = True
                    save_npc_alt_ref(item["name"], img, metadata=meta)
                else:
                    meta["alt_universe"] = False
                    save_npc_ref(item["name"], img, metadata=meta)
                saved += 1
            except Exception:
                failed += 1

        sample_text = "\n".join(f"- {s}" for s in samples[-12:]) if samples else "- none"
        mode = "DRY RUN" if dry_run else "SAVED"
        skipped_note = f" (name mismatch: {name_skipped})" if name_skipped else ""
        await interaction.followup.send(
            f"Backfill {mode} complete\n"
            f"Channel: `{getattr(channel, 'name', scan_channel_id)}`\n"
            f"Target: `{target}` | scanned: **{scanned}** | matched: **{len(matches)}**\n"
            f"Saved: **{saved}** | skipped: **{skipped}**{skipped_note} | failed: **{failed}**\n\n"
            f"Recent matches:\n{sample_text}",
            ephemeral=True,
        )
