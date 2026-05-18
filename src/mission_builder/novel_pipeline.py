"""
novel_pipeline.py — Full novel-to-box-set mission module generator.

Pipeline:
  Pass 1 — BobAgent writes the novel, chapter by chapter (70k-100k words)
  Pass 2 — ProAuthorReviewerAgent reviews and tightens each chapter
  Pass 3 — BookToModuleAgent converts the novel to a D&D box set
            (DM Guide, Module, Players Guide, Maps list)
  Pass 4 — DNDExpertAgent + DNDVeteranAgent produce the Chart Pack
            (monsters, NPC stats, rumors, encounter tables, loot tables)

All progress is logged in real-time to src.log with word counts and previews.
Output is written to generated_modules/<title>/ as separate markdown files.
Maps are generated via A1111 + DD_Table_RPG LoRA and indexed in image_refs DB.
"""

from __future__ import annotations

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

OUTPUT_BASE = Path(__file__).resolve().parent.parent.parent / "generated_modules"


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------

def _gather_novel_context(mission: dict) -> dict:
    """Pull campaign context needed to seed the novel."""
    from src.mission_builder import gather_context
    return gather_context(mission)


def _safe_filename(text: str, maxlen: int = 50) -> str:
    return re.sub(r"[^\w\s-]", "", text).strip().replace(" ", "_")[:maxlen]


# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------

def _make_output_dir(title: str) -> Path:
    safe = _safe_filename(title)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    out  = OUTPUT_BASE / f"{safe}_{ts}"
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------------------------------------------------------------------------
# Pass 1 — Bob writes the novel
# ---------------------------------------------------------------------------

async def _pass1_write_novel(ctx: dict, out_dir: Path, force: bool = True) -> list[dict]:
    """
    Bob writes the full novel chapter by chapter.

    Returns a list of chapter dicts:
      { "num": int, "title": str, "word_count": int, "text": str }
    """
    from src.agents.learning_agents import BobAgent
    from src.mission_builder.novel_outline import build_novel_outline

    title         = ctx["title"]
    faction       = ctx["faction"]
    mission_body  = ctx["body"]
    npc_block     = ctx["npc_block"]
    news          = ctx["news_memory"][:2000]
    location      = ctx["primary_location"]
    personal_for  = ctx.get("personal_for", "")
    char_info     = ctx.get("char_info", "")

    # Character identity block — critical so Bob writes the right protagonist
    char_block = ""
    if personal_for and char_info:
        char_block = (
            f"PROTAGONIST — THIS MISSION IS PERSONAL FOR: {personal_for}\n"
            f"{char_info}\n\n"
            f"CRITICAL: Write this character as the lead protagonist throughout the entire novel. "
            f"Use their name, race, class, backstory, and personality as described above. "
            f"Do NOT invent a different character. Do NOT write a generic hero with a dagger. "
            f"This is {personal_for}'s story.\n\n"
        )
    elif personal_for:
        char_block = (
            f"PROTAGONIST: {personal_for} — personal mission.\n"
            f"Write {personal_for} as the lead protagonist. Use their name consistently.\n\n"
        )

    logger.info("=" * 70)
    logger.info(f"[BOB] PASS 1 — Novel writing begins: {title!r}")
    logger.info(f"[BOB] Faction: {faction} | Location: {location}")
    logger.info("=" * 70)

    # Step 1a: Build an outline (chapter-by-chapter plan)
    outline = await build_novel_outline(ctx, force=force)
    if not outline:
        logger.error("[BOB] Outline generation failed — cannot continue")
        return []

    logger.info(f"[BOB] Outline ready — {len(outline)} chapters planned")
    (out_dir / "outline.md").write_text(
        f"# {title} — Novel Outline\n\n" + "\n\n".join(
            f"## Chapter {c['num']}: {c['title']}\n{c['summary']}"
            for c in outline
        ),
        encoding="utf-8",
    )

    # Step 1b: Write each chapter
    chapters: list[dict] = []
    prev_summary = ""
    bob = BobAgent()

    try:
        for ch in outline:
            ch_num   = ch["num"]
            ch_title = ch["title"]
            ch_plan  = ch["summary"]

            logger.info(f"[BOB] Writing Chapter {ch_num}: {ch_title!r} ...")

            prompt = (
                f"NOVEL: {title}\n"
                f"SETTING: The Undercity — a vast disk city under a dome, "
                f"with the Tower of Last Chance piercing the center. "
                f"Faction: {faction}. Primary location: {location}.\n\n"
                + char_block
                + f"MISSION CONTEXT:\n{mission_body}\n\n"
                f"KEY NPCS IN THIS STORY:\n{npc_block}\n\n"
                f"RECENT CITY EVENTS:\n{news}\n\n"
                f"CHAPTER {ch_num} OF {len(outline)}: {ch_title}\n\n"
                f"CHAPTER PLAN:\n{ch_plan}\n\n"
                + (f"PREVIOUS CHAPTER SUMMARY:\n{prev_summary}\n\n" if prev_summary else "")
                + "Write this chapter now. R.A. Salvatore style — visceral action, "
                  "internal character monologue, specific sensory detail. "
                  "Minimum 3,500 words. No chapter headers. No meta-commentary. "
                  "Pure prose. Use all named NPCs from the roster — do not invent replacements."
            )

            resp = await bob.complete(prompt=prompt, force=force)

            if resp.success and resp.content and len(resp.content.split()) >= 500:
                text = resp.content.strip()
                wc   = len(text.split())
                chapters.append({
                    "num":        ch_num,
                    "title":      ch_title,
                    "word_count": wc,
                    "text":       text,
                })
                # Save chapter to disk as styled HTML
                from src.mission_builder.html_renderer import render_chapter as _rc
                ch_html = _rc(ch_num, ch_title, title, text, faction)
                ch_file = out_dir / f"chapter_{ch_num:02d}.html"
                ch_file.write_text(ch_html, encoding="utf-8")
                # Build summary for next chapter's context
                prev_summary = text[:1200] + "..." if len(text) > 1200 else text

                preview = text[:120].replace("\n", " ")
                logger.info(
                    f"[BOB]   Chapter {ch_num} done — {wc:,} words | {preview!r}..."
                )
            else:
                logger.warning(
                    f"[BOB]   Chapter {ch_num} FAILED or too short — skipping"
                )
    finally:
        await bob.close()

    total_words = sum(c["word_count"] for c in chapters)
    logger.info(f"[BOB] Pass 1 complete — {len(chapters)} chapters, {total_words:,} words total")
    logger.info(
        "[BOB] Per chapter: "
        + " | ".join(f"Ch{c['num']}={c['word_count']:,}w" for c in chapters)
    )

    return chapters


# ---------------------------------------------------------------------------
# Pass 2 — ProAuthorReviewer tightens the novel
# ---------------------------------------------------------------------------

async def _pass2_review_novel(
    chapters: list[dict], out_dir: Path, force: bool = True
) -> list[dict]:
    """
    ProAuthorReviewerAgent reviews each chapter and returns revised versions.
    """
    from src.agents.learning_agents import ProAuthorReviewerAgent

    logger.info("=" * 70)
    logger.info("[REVIEWER] PASS 2 — Editorial review begins")
    logger.info("=" * 70)

    reviewed: list[dict] = []
    reviewer = ProAuthorReviewerAgent()

    try:
        for ch in chapters:
            ch_num   = ch["num"]
            ch_title = ch["title"]

            logger.info(f"[REVIEWER] Reviewing Chapter {ch_num}: {ch_title!r} ...")

            prompt = (
                f"Chapter {ch_num}: {ch_title}\n\n"
                f"WORD COUNT: {ch['word_count']:,}\n\n"
                f"{ch['text']}"
            )

            resp = await reviewer.complete(prompt=prompt, force=force)

            if resp.success and resp.content and len(resp.content.split()) >= 400:
                # Split revised chapter from editorial note (divided by ---)
                parts    = resp.content.split("---", 1)
                rev_text = parts[0].strip()
                ed_note  = parts[1].strip() if len(parts) > 1 else ""
                wc       = len(rev_text.split())

                reviewed.append({
                    "num":        ch_num,
                    "title":      ch_title,
                    "word_count": wc,
                    "text":       rev_text,
                    "ed_note":    ed_note,
                })

                # Save revised chapter as HTML (overwrites first-draft file)
                from src.mission_builder.html_renderer import render_chapter as _rc2
                ed_suffix = f"\n\n---\n\n*Editorial note: {ed_note}*" if ed_note else ""
                ch_html = _rc2(ch_num, ch_title, "", rev_text + ed_suffix, "")
                ch_file = out_dir / f"chapter_{ch_num:02d}.html"
                ch_file.write_text(ch_html, encoding="utf-8")
                logger.info(
                    f"[REVIEWER]   Ch {ch_num} reviewed — "
                    f"{ch['word_count']:,}w → {wc:,}w"
                    + (f" | Note: {ed_note[:80]!r}" if ed_note else "")
                )
            else:
                logger.warning(
                    f"[REVIEWER]   Ch {ch_num} review failed — keeping original"
                )
                reviewed.append(ch)
    finally:
        await reviewer.close()

    total = sum(c["word_count"] for c in reviewed)
    logger.info(f"[REVIEWER] Pass 2 complete — {total:,} words after review")

    return reviewed


# ---------------------------------------------------------------------------
# Pass 3 — BookToModuleAgent builds the box set
# ---------------------------------------------------------------------------

async def _pass3_build_box_set(
    chapters: list[dict], ctx: dict, out_dir: Path, force: bool = True
) -> dict[str, Path]:
    """
    BookToModuleAgent converts the novel to a D&D box set.
    Returns dict mapping component name to output Path.
    """
    from src.agents.learning_agents import BookToModuleAgent

    logger.info("=" * 70)
    logger.info("[BOX SET] PASS 3 — Converting novel to box set")
    logger.info("=" * 70)

    title   = ctx["title"]
    faction = ctx["faction"]

    # Build a condensed novel synopsis for context
    synopsis = "\n\n".join(
        f"CHAPTER {c['num']} — {c['title']}:\n"
        + c["text"][:1500] + ("..." if len(c["text"]) > 1500 else "")
        for c in chapters
    )

    converter = BookToModuleAgent()
    output_paths: dict[str, Path] = {}

    sections = [
        (
            "dm_guide",
            "DM GUIDE",
            "Write the DM Guide. Include: Adventure Background (what happened before the players arrived), "
            "Adventure Summary (one paragraph per act), Secret Truths (what the DM knows that players don't), "
            "Faction Stakes (what each faction wants from this mission and what they lose if it fails), "
            "Adjusting Difficulty (specific changes for small parties, large parties, stronger parties), "
            "Pacing Notes (how long each act should take), and Running the Final Encounter (tactical tips). "
            "Use ## for sections, ### for subsections. Be specific — name the NPCs, name the locations, name the stakes.",
        ),
        (
            "module",
            "MODULE",
            "You have the full novel to draw from. USE IT. Pull the actual NPC dialogue, "
            "scene descriptions, clue moments, and dramatic beats directly from the novel text. "
            "Do not invent generic D&D content — adapt what the novel already built.\n\n"
            "Write the complete play-ready module in official D&D one-shot format. "
            "Structure it as three acts:\n"
            "ACT 1 (15-20 min, 1-2 scenes): The hook — who is hiring, what's the job, why NOW.\n"
            "ACT 2 (50-60 min, 2-3 scenes): The adventure — exploration, investigation, conversation, minor combat.\n"
            "ACT 3 (30-40 min, 1-2 scenes): The climax — the main encounter with full stat blocks.\n"
            "RESOLUTION (10-15 min): Rewards, consequences, story hooks.\n\n"
            "For EACH scene use this exact format:\n\n"
            "### Scene N: [Name from the novel]\n"
            "**N - [Location name]**\n\n"
            "📖 READ ALOUD:\n"
            "[3-4 sentences pulled from or inspired by the novel's description of this moment. "
            "Sight, sound, smell. End with something that invites player action — "
            "a person who looks at them, a sound in the distance, a door that stands open.]\n\n"
            "📝 DM NOTES:\n"
            "- [What's really happening here that players don't know yet]\n"
            "- [What information is physically present — readable, visible, findable]\n"
            "- [The one thing that makes this scene connect to the next scene]\n\n"
            "👤 NPCs PRESENT:\n"
            "- [Name] — [race/role] — [What they want right now. What they KNOW. What they HIDE. "
            "Include 2-3 lines of actual dialogue the DM can use verbatim, drawn from the novel.]\n\n"
            "CONVERSATION BRANCHES (critical — this is what was missing before):\n"
            "If players ask about [topic]: [What the NPC says. What skill check reveals the lie/truth. DC X.]\n"
            "If players ask about [topic 2]: [What the NPC reveals freely vs. what needs a persuasion check.]\n"
            "The NPC gives Clue A automatically. Clue B requires DC [X] [Skill]. Clue C requires creative roleplay.\n\n"
            "🎲 MECHANICS:\n"
            "- [Skill] DC [X]: [Exactly what a success reveals — a name, a location, a motive, not 'more info']\n"
            "- [Skill] DC [X]: [Failure consequence if relevant]\n"
            "- Combat: [Summary if combat possible]\n\n"
            "⚡ WHAT HAPPENS:\n"
            "- [Trigger 1]: [Result]\n"
            "- [Trigger 2]: [Result]\n"
            "- [If players do nothing]: [What happens next anyway — scenes don't stall]\n\n"
            "➡️ TRANSITION: [1 clear sentence: what the players learn/see/hear that makes them want to go to the next scene. "
            "Never 'they proceed' — give them a reason.]\n\n"
            "---\n\n"
            "STAT BLOCKS: Place EVERY enemy stat block immediately after the scene where they first appear. "
            "Never in an appendix. Full D&D 5e 2024 format: Name, Type/Alignment, AC, HP (dice), Speed, "
            "STR/DEX/CON/INT/WIS/CHA with modifiers, Saves, Skills, Senses, CR, Actions, Reactions. "
            "Add TACTICS: what the enemy does on round 1, when bloodied, when they flee or surrender.\n\n"
            "BATTLEFIELD: Every combat scene gets: 3-sentence description + bullet list of "
            "cover/elevation/hazards/interactable objects + lighting conditions.",
        ),
        (
            "players_guide",
            "PLAYERS GUIDE",
            "Write the Players Guide. Include: Setting Introduction (what the players know about the Undercity), "
            "The Contract (what they've been hired to do — only public information, no secrets), "
            "Key Contacts (names and how to reach them — no hidden motives), "
            "Known Dangers (faction threats, environmental hazards they can research), "
            "Reward Structure (EC amounts, reputation gains, bonus objectives), "
            "and 3 Hooks (personal reasons a player character might care about this job). "
            "Write this as if handing it to players before the session. Clear, exciting, no spoilers.",
        ),
        (
            "maps",
            "MAPS",
            "Output a JSON array of map locations for this module. "
            "Each entry is one battlemap or key location that needs a visual map. "
            "Output ONLY valid JSON — no markdown, no explanation, no preamble. "
            "Format:\n"
            '[\n'
            '  {\n'
            '    "name": "Location name",\n'
            '    "type": "interior|exterior|dungeon|rooftop|sewer|warehouse",\n'
            '    "description": "2-3 sentence atmospheric description for the artist",\n'
            '    "size": "30x30|40x40|20x20",\n'
            '    "features": ["feature1","feature2","feature3"],\n'
            '    "ascii": "....................\\n.####.####.####..\\n.#..#....#..#..#.\\n.................."\n'
            '  }\n'
            ']\n'
            "The ascii field is a top-down grid: # = wall, . = floor, D = door, W = window, "
            "T = table, B = barrel/box, P = pillar, S = stairs, ^ = elevation, ~ = water. "
            "Maximum 6 maps. Include the final combat area, the main investigation location, and 1-2 other key scenes.",
        ),
    ]

    try:
        for slug, label, instruction in sections:
            logger.info(f"[BOX SET]   Building {label} ...")

            prompt = (
                f"NOVEL: {title}\n"
                f"FACTION: {faction}\n\n"
                f"NOVEL CONTENT:\n{synopsis}\n\n"
                f"TASK: {instruction}\n\n"
                f"Output structured markdown. ## for sections, ### for subsections. "
                f"Specific names. No placeholders."
            )

            resp = await converter.complete(prompt=prompt, force=force)

            if resp.success and resp.content:
                text = resp.content.strip()

                if slug == "maps":
                    # Save raw JSON manifest for Pass 5 to read directly
                    raw = text
                    # Strip any accidental markdown fences
                    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
                    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
                    raw = raw.strip()
                    manifest_path = out_dir / "maps_manifest.json"
                    try:
                        import json as _jv
                        _jv.loads(raw)  # validate
                        manifest_path.write_text(raw, encoding="utf-8")
                        logger.info(f"[BOX SET]   MAPS manifest saved → {manifest_path.name}")
                    except Exception as _je:
                        logger.warning(f"[BOX SET]   Maps JSON invalid: {_je} — saving raw anyway")
                        manifest_path.write_text(raw, encoding="utf-8")
                    # Still render as HTML for reading
                    from src.mission_builder.html_renderer import render_component as _rcomp
                    html = _rcomp(label, title, "*(Map manifest — see maps_manifest.json)*\n\n" + raw, faction)
                    path = out_dir / f"{slug}.html"
                    path.write_text(html, encoding="utf-8")
                    output_paths[slug] = manifest_path  # point to JSON, not HTML
                else:
                    from src.mission_builder.html_renderer import render_component as _rcomp
                    html = _rcomp(label, title, text, faction)
                    path = out_dir / f"{slug}.html"
                    path.write_text(html, encoding="utf-8")
                    output_paths[slug] = path

                wc = len(text.split())
                logger.info(f"[BOX SET]   {label} done — {wc:,} words → {out_dir.name}/{slug}.*")
            else:
                logger.warning(f"[BOX SET]   {label} generation failed")
    finally:
        await converter.close()

    logger.info(f"[BOX SET] Pass 3 complete — {len(output_paths)} components built")

    return output_paths


# ---------------------------------------------------------------------------
# Pass 4 — Chart Pack (DNDExpert + DNDVeteran)
# ---------------------------------------------------------------------------

async def _pass4_chart_pack(
    chapters: list[dict], ctx: dict, out_dir: Path, force: bool = True
) -> Optional[Path]:
    """
    DNDExpertAgent + DNDVeteranAgent produce the chart pack:
    - Monster stat blocks
    - NPC stats
    - Encounter tables
    - Loot tables
    - Rumor chart (d8)
    - Skill check reference
    """
    from src.agents.learning_agents import DNDExpertAgent, DNDVeteranAgent

    logger.info("=" * 70)
    logger.info("[CHARTS] PASS 4 — Chart pack generation begins")
    logger.info("=" * 70)

    title   = ctx["title"]
    faction = ctx["faction"]
    cr      = ctx.get("cr", 5)
    tier    = ctx.get("tier", "standard")

    # Condense novel for chart context — hard cap to avoid Ollama OOM
    # 300 chars per chapter, max 12 chapters, keeps total under ~6k chars
    combat_context = "\n\n".join(
        f"Ch {c['num']}: {c['title']}\n" + c["text"][:300]
        for c in chapters[:12]
    )

    # ── DNDExpert: Stat blocks + encounter tables ──────────────────────────
    logger.info("[CHARTS]   DNDExpert building stat blocks and encounter tables ...")
    expert = DNDExpertAgent()
    stat_blocks = ""
    try:
        resp = await expert.complete(
            prompt=(
                f"NOVEL: {title} | FACTION: {faction} | CR: {cr} | TIER: {tier}\n\n"
                f"NOVEL COMBAT SCENES:\n{combat_context}\n\n"
                "Build the Mechanics Pack for this mission. Output structured markdown:\n\n"
                "## Monster Stat Blocks\n"
                "Full D&D 5e 2024 stat blocks for every enemy type that appears in the novel. "
                "Every field. No shortcuts. Include tactical notes.\n\n"
                "## NPC Stats\n"
                "Combat-relevant stats for named NPCs. Use the >> prefix for each line "
                "(these render as parchment scroll boxes in the final document).\n\n"
                "## Encounter Tables\n"
                "| d8 | Encounter | Location | Difficulty |\n"
                "Eight rows. Encounters drawn from the novel's locations.\n\n"
                "## Skill Check Reference\n"
                "| Skill | DC | What Success Achieves | Where in Story |\n"
                "Every meaningful skill check in the novel, organized by chapter.\n\n"
                "## Loot Tables\n"
                "| d6 | Item | Value | Notes |\n"
                "Appropriate for CR " + str(cr) + ". Include one unique item from the story."
            ),
            force=force,
        )
        if resp.success and resp.content:
            stat_blocks = resp.content.strip()
            wc = len(stat_blocks.split())
            logger.info(f"[CHARTS]   Stat blocks + tables done — {wc:,} words")
    except Exception as e:
        logger.warning(f"[CHARTS]   DNDExpert chart pack failed: {e}")
    finally:
        await expert.close()

    # ── DNDVeteran: Rumors + DM complications ──────────────────────────────
    logger.info("[CHARTS]   DNDVeteran building rumor chart and DM tables ...")
    veteran = DNDVeteranAgent()
    veteran_charts = ""
    try:
        resp = await veteran.complete(
            prompt=(
                f"NOVEL: {title} | FACTION: {faction}\n\n"
                f"NOVEL SUMMARY:\n" +
                "\n".join(
                    f"Ch {c['num']}: {c['title']} — {c['text'][:400]}..."
                    for c in chapters
                ) +
                "\n\nBuild the DM Toolkit for this mission. Output structured markdown:\n\n"
                "## Rumor Chart (d8)\n"
                "| d8 | Rumor | Source | True? |\n"
                "Eight rows. Mix true, half-true, and false. Each sounds like it came from a "
                "specific person with a specific reason to say it.\n\n"
                "## DM Complication Table (d6)\n"
                "| d6 | Complication | When | Effect |\n"
                "Six complications specific to this story. Every row names something concrete.\n\n"
                "## Power Player Adjustments\n"
                "Five specific changes for optimized parties. Name the scene being adjusted.\n\n"
                "## Story Seeds (Post-Mission)\n"
                "Three one-line hooks for follow-on missions. A name, a place, an action."
            ),
            force=force,
        )
        if resp.success and resp.content:
            veteran_charts = resp.content.strip()
            wc = len(veteran_charts.split())
            logger.info(f"[CHARTS]   Rumor chart + DM tables done — {wc:,} words")
    except Exception as e:
        logger.warning(f"[CHARTS]   DNDVeteran chart pack failed: {e}")
    finally:
        await veteran.close()

    # ── Assemble chart pack as HTML ────────────────────────────────────────
    if stat_blocks or veteran_charts:
        combined_md = ""
        if stat_blocks:
            combined_md += stat_blocks + "\n\n"
        if veteran_charts:
            combined_md += veteran_charts
        from src.mission_builder.html_renderer import render_component as _rcc
        path = out_dir / "chart_pack.html"
        path.write_text(_rcc("Chart Pack", title, combined_md, faction), encoding="utf-8")
        logger.info(f"[CHARTS] Pass 4 complete — chart pack written to {path.name}")
        return path

    logger.warning("[CHARTS] Pass 4 produced no output")
    return None


# ---------------------------------------------------------------------------
# Map generation — Pass 5
# ---------------------------------------------------------------------------

async def _pass5_generate_maps(
    box_set_paths: dict[str, Path],
    title: str,
    out_dir: Path,
) -> list[Path]:
    """
    Read maps_manifest.json from Pass 3 and generate each map
    via A1111 + DD_Table_RPG LoRA. Index all maps in image_refs DB.
    """
    from src.mission_builder.image_generator import generate_location_map
    from src.mission_builder.vtt_renderer import save_vtt_battlemap_bytes
    from src.news_feed import a1111_lock
    from src.db_api import raw_query, raw_execute
    import json as _json

    # maps_manifest.json is the authoritative source (written by Pass 3)
    manifest_path = out_dir / "maps_manifest.json"
    if not manifest_path.exists():
        logger.warning("[MAPS] No maps_manifest.json found — skipping map generation")
        return []

    try:
        map_entries = _json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(map_entries, list):
            map_entries = []
    except Exception as e:
        logger.warning(f"[MAPS] maps_manifest.json parse error: {e} — skipping")
        return []

    if not map_entries:
        logger.info("[MAPS] No parseable map entries found in maps.md")
        return []

    logger.info(f"[MAPS] Pass 5 — Generating {len(map_entries)} maps ...")
    maps_dir  = out_dir / "maps"
    maps_dir.mkdir(exist_ok=True)
    map_paths: list[Path] = []

    for loc in map_entries[:6]:  # cap at 6 maps per module
        loc_name   = loc.get("name", "Unknown Location")
        loc_type   = loc.get("type", "interior")
        loc_desc   = loc.get("description", "")
        loc_feats  = ", ".join(loc.get("features", []))
        loc_grid   = loc.get("ascii", loc.get("ascii_grid", ""))
        loc_size   = loc.get("size", "30x30")
        loc_prompt = f"{loc_desc} {loc_feats}".strip() or loc_name

        # Check DB cache first
        cached = raw_query(
            "SELECT image_path FROM image_refs "
            "WHERE entity_type='location_map' AND entity_name=%s LIMIT 1",
            (loc_name,),
        )
        if cached and Path(cached[0]["image_path"]).exists():
            map_paths.append(Path(cached[0]["image_path"]))
            logger.info(f"[MAPS]   Reused cached map: {loc_name!r}")
            raw_execute(
                "UPDATE image_refs SET ref_count=ref_count+1, updated_at=NOW() "
                "WHERE entity_type='location_map' AND entity_name=%s",
                (loc_name,),
            )
            continue

        logger.info(f"[MAPS]   Generating: {loc_name!r} ({loc_type})")
        try:
            from src.resource_cop import wait_for_a1111_turn
            decision = await wait_for_a1111_turn("novel_location_map", max_wait_seconds=60)
            if not decision.run_now:
                logger.info(f"[MAPS]   A1111 deferred by resource cop for {loc_name!r}: {decision.reason}")
                continue
            async with a1111_lock:
                img_bytes = await generate_location_map(
                    loc_name, loc_prompt, loc_type, ascii_grid=loc_grid
                )
            if img_bytes:
                safe_name = _safe_filename(loc_name, 30)
                ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
                map_file  = maps_dir / f"{safe_name}_{ts}.png"
                map_context = {
                    "title": loc_name,
                    "location": loc_name,
                    "description": loc_desc,
                    "prompt": loc_prompt,
                    "kind": loc_type,
                }
                save_vtt_battlemap_bytes(map_file, img_bytes, context=map_context)
                map_paths.append(map_file)
                raw_execute(
                    "INSERT INTO image_refs "
                    "(entity_type, entity_name, image_path, metadata_json) "
                    "VALUES ('location_map', %s, %s, %s) "
                    "ON DUPLICATE KEY UPDATE image_path=VALUES(image_path), "
                    "ref_count=ref_count+1, updated_at=NOW()",
                    (loc_name, str(map_file),
                     json.dumps({"type": loc_type, "prompt": loc_prompt[:200], "mission_title": title})),
                )
                logger.info(f"[MAPS]   Done: {map_file.name} ({len(img_bytes)//1024}KB)")
        except Exception as e:
            logger.warning(f"[MAPS]   Failed for {loc_name!r}: {e}")

    logger.info(f"[MAPS] Pass 5 complete — {len(map_paths)} maps generated")
    return map_paths


# ---------------------------------------------------------------------------
# Final assembly — index.md + Discord-ready metadata
# ---------------------------------------------------------------------------

def _write_index(
    out_dir: Path,
    title: str,
    ctx: dict,
    chapters: list[dict],
    box_set_paths: dict[str, Path],
    chart_pack_path: Optional[Path],
    map_paths: list[Path],
) -> Path:
    """Write an index.html — the landing page for the full module output."""
    from src.mission_builder.html_renderer import render_index as _ri

    components = [(slug, p.name) for slug, p in box_set_paths.items()]
    chart_name = chart_pack_path.name if chart_pack_path else None

    html = _ri(
        novel_title=title,
        faction=ctx["faction"],
        tier=ctx["tier"],
        cr=ctx.get("cr", "?"),
        player_name=ctx.get("personal_for") or "Open",
        chapters=chapters,
        components=components,
        chart_pack=chart_name,
        map_count=len(map_paths),
    )

    index_path = out_dir / "index.html"
    index_path.write_text(html, encoding="utf-8")
    logger.info(f"[INDEX] Written: {index_path}")
    return index_path


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def generate_novel_module(mission: dict, player_name: str = "") -> Optional[Path]:
    """
    Full novel pipeline entry point. Called from generate_module().

    Returns Path to index.md (output directory) or None on failure.
    """
    from src.ollama_busy import mark_priority_busy, unmark_priority_busy

    title = mission.get("title", "Unknown Mission")
    logger.info("=" * 70)
    logger.info(f"[PIPELINE] Novel module starting: {title!r}")
    logger.info(f"[PIPELINE] Player: {player_name or 'Open'}")
    logger.info("=" * 70)

    ctx     = _gather_novel_context(mission)
    ctx["personal_for"] = player_name
    out_dir = _make_output_dir(title)

    logger.info(f"[PIPELINE] Output directory: {out_dir}")

    mark_priority_busy(f"novel pipeline: {title}")
    try:
        # Pass 1: Write the novel
        chapters = await _pass1_write_novel(ctx, out_dir, force=True)
        if not chapters:
            logger.error("[PIPELINE] Pass 1 failed — aborting")
            return None

        # Pass 2: Review the novel
        chapters = await _pass2_review_novel(chapters, out_dir, force=True)

        # Pass 3: Build box set
        box_set_paths = await _pass3_build_box_set(chapters, ctx, out_dir, force=True)

        # Pass 4: Chart pack (sequential after box set — same Ollama instance)
        chart_pack_path = await _pass4_chart_pack(chapters, ctx, out_dir, force=True)

        # Pass 5: Generate maps (A1111 — separate from Ollama, runs after)
        map_paths = await _pass5_generate_maps(box_set_paths, title, out_dir)

        # Write index
        index_path = _write_index(
            out_dir, title, ctx, chapters, box_set_paths, chart_pack_path, map_paths
        )

        total_words = sum(c["word_count"] for c in chapters)

        # ZIP the entire output directory for easy delivery
        import zipfile
        zip_path = out_dir.parent / f"{out_dir.name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in sorted(out_dir.rglob("*")):
                if file.is_file():
                    zf.write(file, arcname=file.relative_to(out_dir.parent))
        zip_kb = zip_path.stat().st_size // 1024
        logger.info(f"[PIPELINE] Zipped → {zip_path.name} ({zip_kb}KB)")

        logger.info("=" * 70)
        logger.info(f"[PIPELINE] COMPLETE: {title!r}")
        logger.info(f"[PIPELINE]   Novel:      {total_words:,} words across {len(chapters)} chapters")
        logger.info(f"[PIPELINE]   Box set:    {len(box_set_paths)} components")
        logger.info(f"[PIPELINE]   Chart pack: {'yes' if chart_pack_path else 'no'}")
        logger.info(f"[PIPELINE]   Maps:       {len(map_paths)} generated")
        logger.info(f"[PIPELINE]   Output dir: {out_dir}")
        logger.info(f"[PIPELINE]   ZIP:        {zip_path.name} ({zip_kb}KB)")
        logger.info("=" * 70)

        # Return the zip path so post_module_to_channel can attach it
        ctx["zip_path"] = str(zip_path)
        return index_path

    finally:
        unmark_priority_busy()
