"""
mission_builder — Complete D&D mission generation system with JSON + images.

Refactored system (Steps 1-4) providing structured JSON output with full image support.

High-level API exports for easy integration:
    generate_mission()                  - Sync mission generation
    generate_mission_async()            - Async mission generation
    generate_mission_with_images()      - Mission + battle maps (async)
    generate_mission_with_images_sync() - Mission + battle maps (sync)
    generate_complete_mission()         - Full generation to disk
    
For advanced usage:
    MissionJsonBuilder                  - Fluent mission builder
    generate_module_json()              - Raw 4-pass Ollama generation
    generate_dungeon_tiles_for_rooms()  - Tile generation
    stitch_dungeon_map()                - Map composite stitching
    
Schemas and validation:
    MissionModule, ImageAsset, DungeonRoom, NPC, etc.

SKILLS SYSTEM (project-wide):
    Skills are now centralized in src.skills and exposed here for convenience.
    Use from src or from here:
        from src.mission_builder import (
            load_all_skills,
            set_use_skills,
            build_system_prompt_with_skills,
        )
    Or better: use from src directly:
        from src import load_all_skills, set_use_skills

LEGACY MODULES (still available):
- locations.py: Gazetteer integration for real named places
- leads.py: Investigation leads system
- encounters.py: Combat design and stat blocks
- npcs.py: NPC generation and dialogue
"""

from __future__ import annotations

import os
import re
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

# Skills system — re-exported for convenience
from src.skills import (
    load_all_skills,
    set_use_skills,
    get_skill_for_task,
    build_system_prompt_with_skills,
    list_available_skills,
    get_skill_content,
    enhance_generation_with_skills,
)

from .locations import (
    load_gazetteer,
    build_location_context,
    find_location_for_mission,
    get_establishments_for_leads,
    format_lead_locations,
)
from .leads import (
    generate_investigation_leads,
    format_leads_for_prompt,
)
from .encounters import (
    get_cr,
    get_max_pc_level,
    get_party_size,
    get_encounter_budget,
    format_encounter_guidelines,
    build_encounter_prompt_block,
)


def _fit_ctx(prompt: str, reply_tokens: int) -> int:
    """Size the Ollama context window to the prompt + planned reply. With no
    num_ctx set, Ollama uses a small default and silently truncates either the
    oversized prompt or the long reply (yielding empty/unparseable output).
    Only raises; capped at 32k. Local to this module by the no-shared-helpers
    rule."""
    needed = len(prompt) // 4 + reply_tokens + 768
    for cand in (8192, 12288, 16384, 24576, 32768):
        if cand >= needed:
            return cand
    return 32768


async def _ollama_generate(
    prompt: str,
    system: str = "",
    timeout: float = 300.0,
    max_tokens: int = 1400,
) -> str:
    """Compatibility helper for legacy JSON/title generation paths."""
    from src.ollama_queue import call_ollama

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    data = await call_ollama(
        {
            "model": os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"),
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.75,
                "num_predict": max_tokens,
                "think": False,
                "num_ctx": _fit_ctx(system + prompt, max_tokens),
            },
        },
        timeout=timeout,
        caller="mission_builder",
        force=True,
    )
    return ((data.get("message") or {}).get("content") or "").strip()


def _post_process_module_text(text: str, forbidden_names: Optional[list[str]] = None) -> str:
    """Small safety pass used by the legacy JSON module generator."""
    cleaned = str(text or "")
    for name in forbidden_names or []:
        if name:
            cleaned = re.sub(re.escape(name), "the party", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bREAD ALOUD\s*:?", "Scene Description:", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bRead Aloud\s*:?", "Scene Description:", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()

from .npcs import (
    get_relevant_npcs,
    format_npc_block,
    build_npc_prompt_block,
    format_quest_giver_guidance,
)
from .rewards import (
    format_rewards_block,
    format_consequences_prompt,
    build_loot_table,
)
from .docx_builder import (
    build_docx,
    format_module_for_docx,
    validate_module_data,
    get_output_dir,
)
from .maps import (
    extract_map_scenes,
    generate_vtt_map,
    generate_module_maps,
    post_maps_to_channel,
)
from .schemas import (
    validate_mission_module,
    MissionModule,
)
from .mission_json_builder import (
    MissionJsonBuilder,
    create_mission_module,
)

# json_generator is imported on-demand to avoid circular imports

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "campaign_docs"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "generated_modules"

CR_TO_LEVEL = {i: i for i in range(1, 21)}

# ---------------------------------------------------------------------------
# Context gathering
# ---------------------------------------------------------------------------

def gather_context(mission: dict) -> dict:
    """Pull all relevant campaign context for module generation."""
    faction = mission.get("faction", "")
    tier = mission.get("tier", "standard")
    title = mission.get("title", "")
    body = mission.get("body", "")
    personal_for = mission.get("personal_for", "")
    mission_type = mission.get("type", tier)

    # Get relevant NPCs
    relevant_npcs = get_relevant_npcs(faction)
    npc_block = format_npc_block(relevant_npcs)

    # News memory for plot hooks — from MySQL
    news = ""
    try:
        from src.db_api import raw_query as _rq_news
        _rows = _rq_news(
            "SELECT facts FROM news_memory ORDER BY id DESC LIMIT 10"
        ) or []
        news = "\n".join(r.get("facts") or "" for r in _rows if r.get("facts"))[:6000]
    except Exception:
        pass

    # Faction reputation — from MySQL
    faction_rep = ""
    try:
        from src.db_api import get_all_faction_reputations as _get_rep
        for r in (_get_rep() or []):
            if faction.lower() in r["faction_name"].lower():
                faction_rep = f"{r['faction_name']}: tier={r['tier']}, points={r['reputation_score']}"
                break
    except Exception:
        pass  # faction_reputation.json file fallback removed — DB is authoritative

    # Character info (if personal mission) — from MySQL player_characters
    char_info = ""
    if personal_for:
        try:
            from src.db_api import get_character_memory_text as _gcmt
            chars_text = (_gcmt() or "")[:3000]
        except Exception:
            chars_text = ""
        blocks = chars_text.split("---CHARACTER---")
        for block in blocks:
            if personal_for.lower() in block.lower():
                char_info = block.strip()
                break

    # Active rift state — from MySQL
    rift_context = ""
    try:
        from src.db_api import get_rift_state as _get_rift
        rift_state = _get_rift()
        if rift_state and rift_state.get("active"):
            effects = rift_state.get("effects_json") or {}
            if isinstance(effects, str):
                import json as _j
                effects = _j.loads(effects)
            rifts = effects.get("rifts", []) if isinstance(effects, dict) else []
            active_rifts = [r for r in rifts if not r.get("resolved")]
            if active_rifts:
                rift_context = "Active Rifts: " + "; ".join(
                    f"{r.get('location', '?')} (stage: {r.get('stage', '?')})"
                    for r in active_rifts
                )
    except Exception:
        logger.warning("Rift context unavailable from DB; skipping stale file fallback")

    cr = get_cr(tier)
    max_pc_level = get_max_pc_level()
    party_size = get_party_size()

    # NEW: Get location context from gazetteer
    primary_location, location_info = find_location_for_mission(
        faction=faction,
        tier=tier,
    )
    location_context = build_location_context(primary_location, include_underground=True)

    # NEW: Generate investigation leads
    leads = generate_investigation_leads(
        faction=faction,
        tier=tier,
        mission_type=mission_type,
        count=3,
    )
    leads_prompt = format_leads_for_prompt(leads, cr)

    # Get establishments for leads
    establishments = get_establishments_for_leads(faction=faction, count=4)
    establishments_context = format_lead_locations(establishments)

    return {
        "mission": mission,
        "faction": faction,
        "tier": tier,
        "mission_type": mission_type,
        "cr": cr,
        "max_pc_level": max_pc_level if max_pc_level > 0 else cr,
        "party_size": party_size,
        "title": title,
        "body": body,
        "personal_for": personal_for,
        "char_info": char_info,
        "npc_block": npc_block,
        "relevant_npcs": relevant_npcs,
        "news_memory": news,
        "faction_rep": faction_rep,
        "rift_context": rift_context,
        # NEW context
        "primary_location": primary_location,
        "location_context": location_context,
        "leads": leads,
        "leads_prompt": leads_prompt,
        "establishments_context": establishments_context,
    }



# Old pipeline removed — see src/mission_builder/novel_pipeline.py


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

async def generate_module(mission: dict, player_name: str = "") -> Optional[Path]:
    """Generate a mission module while recording whole-pipeline lifecycle state."""
    raw_type = (mission.get("type") or mission.get("mission_type") or "").lower().strip()
    from src.resource_cop import (
        append_pipeline_failure,
        finish_pipeline,
        set_pipeline_phase,
        start_pipeline,
    )

    run = await start_pipeline(
        "mission_generation",
        mission_title=mission.get("title") or "Untitled Mission",
        mission_type=raw_type or "published",
        phase="routing",
        player_name=player_name,
        mission_id=mission.get("id") or mission.get("mission_id") or "",
    )
    try:
        result = await _generate_module_routed(mission, player_name)
        if result is None:
            await set_pipeline_phase(run.run_id, "failed", output_path="")
            await append_pipeline_failure(run.run_id, RuntimeError("Pipeline returned no output"))
            return None
        # Inject a named-NPC-voiced Table Talk dialog section into the module for
        # every pipeline. Idempotent: skips published (already has per-scene
        # dialog) and any already-patched module. Non-fatal on failure.
        try:
            from pathlib import Path as _P
            from src.mission_builder.scene_dialogs import inject_module_dialog
            _rp = _P(result)
            _module_html = (_rp if _rp.is_dir() else _rp.parent) / "module.html"
            if _module_html.exists():
                await inject_module_dialog(_module_html, mission)
        except Exception as _dlg_err:
            logger.warning(f"[MODULE] Table Talk dialog injection failed: {_dlg_err}")
        # NPC knowledge cards (Description + Motivation) for the contact and any
        # roster NPC named in the module. Idempotent; skips modules already carrying
        # the cards (e.g. published_pipeline). Non-fatal on failure.
        try:
            from pathlib import Path as _P2
            from src.mission_builder.npc_knowledge_cards import build_module_npc_cards
            _rp2 = _P2(result)
            _mh = (_rp2 if _rp2.is_dir() else _rp2.parent) / "module.html"
            if _mh.exists():
                _html = _mh.read_text(encoding="utf-8")
                if "NPC Knowledge Reference" not in _html:
                    _cards = build_module_npc_cards(_html, mission)
                    if _cards:
                        _anchor = _html.find('<div style="margin:24px 0;border-top:3px solid #1a1a2e;')
                        if _anchor == -1:
                            _anchor = _html.rfind("</body>")
                        _html = (_html + _cards) if _anchor == -1 else (_html[:_anchor] + _cards + _html[_anchor:])
                        _mh.write_text(_html, encoding="utf-8")
                        logger.info("[MODULE] NPC knowledge cards injected into module.html")
        except Exception as _npc_err:
            logger.warning(f"[MODULE] NPC card injection failed: {_npc_err}")
        # Skill Check Cues (contextual setup + success/fail narration) for the
        # checks in the module. Idempotent. Non-fatal on failure.
        try:
            from pathlib import Path as _P3
            from src.mission_builder.scene_dialogs import inject_skill_check_cues
            _rp3 = _P3(result)
            _mh3 = (_rp3 if _rp3.is_dir() else _rp3.parent) / "module.html"
            if _mh3.exists():
                await inject_skill_check_cues(_mh3, mission)
        except Exception as _cue_err:
            logger.warning(f"[MODULE] Skill Check Cues injection failed: {_cue_err}")
        await set_pipeline_phase(run.run_id, "completed", output_path=str(result))
        return result
    except asyncio.CancelledError:
        await set_pipeline_phase(run.run_id, "cancelled")
        raise
    except Exception as exc:
        await set_pipeline_phase(run.run_id, "failed")
        await append_pipeline_failure(run.run_id, exc)
        raise
    finally:
        await finish_pipeline(run.run_id)


async def _generate_module_routed(mission: dict, player_name: str = "") -> Optional[Path]:
    """
    Generate a complete mission module.

    Routes to a type-specific pipeline first; falls back to the table-first
    published pipeline for all unrecognised types. The older novel pipeline is
    still available with MODULE_PIPELINE=novel.
    """
    import re as _re
    from pathlib import Path as _Path
    from datetime import datetime as _dt

    def _out_dir(label: str) -> _Path:
        safe = _re.sub(r"[^\w\s-]", "", mission.get("title") or label).strip().replace(" ", "_")[:50] or label
        base = _Path(__file__).resolve().parent.parent.parent / "generated_modules"
        _mid = mission.get("id") or mission.get("mission_id")
        mid_tag = f"_id{int(_mid)}" if _mid else ""
        ts = _dt.now().strftime('%Y%m%d_%H%M%S_%f')[:19]
        return base / f"{safe}{mid_tag}_{ts}"

    raw_type = (mission.get("type") or mission.get("mission_type") or "").lower().strip()

    # ── Type-specific pipelines (each is fully standalone) ──────────────────
    from src.mission_builder.infestation_pipeline import is_infestation_mission, build_infestation_module
    if is_infestation_mission(raw_type):
        return await build_infestation_module(mission, _out_dir("Infestation"))

    from src.mission_builder.defense_pipeline import is_defense_mission, build_defense_module
    if is_defense_mission(raw_type):
        return await build_defense_module(mission, _out_dir("Defense"))

    from src.mission_builder.gather_pipeline import is_gather_mission, build_gather_module
    if is_gather_mission(raw_type):
        return await build_gather_module(mission, _out_dir("Gathering"))

    from src.mission_builder.battle_pipeline import is_battle_mission, build_battle_module
    if is_battle_mission(raw_type):
        return await build_battle_module(mission, _out_dir("Battle"))

    from src.mission_builder.assault_pipeline import is_assault_mission, build_assault_module
    if is_assault_mission(raw_type):
        return await build_assault_module(mission, _out_dir("Assault"))

    from src.mission_builder.escort_pipeline import is_escort_mission, build_escort_module
    if is_escort_mission(raw_type):
        return await build_escort_module(mission, _out_dir("Escort"))

    from src.mission_builder.recovery_pipeline import is_recovery_mission, build_recovery_module
    if is_recovery_mission(raw_type):
        return await build_recovery_module(mission, _out_dir("Recovery"))

    from src.mission_builder.ambush_pipeline import is_ambush_mission, build_ambush_module
    if is_ambush_mission(raw_type):
        return await build_ambush_module(mission, _out_dir("Ambush"))

    from src.mission_builder.heist_pipeline import is_heist_mission, build_heist_module
    if is_heist_mission(raw_type, mission.get("faction") or mission.get("client_faction") or ""):
        return await build_heist_module(mission, _out_dir("Heist"))

    from src.mission_builder.sabotage_pipeline import is_sabotage_mission, build_sabotage_module
    if is_sabotage_mission(raw_type):
        return await build_sabotage_module(mission, _out_dir("Sabotage"))

    from src.mission_builder.infiltration_pipeline import is_infiltration_mission, build_infiltration_module
    if is_infiltration_mission(raw_type):
        return await build_infiltration_module(mission, _out_dir("Infiltration"))

    from src.mission_builder.rescue_pipeline import is_rescue_mission, build_rescue_module
    if is_rescue_mission(raw_type):
        return await build_rescue_module(mission, _out_dir("Rescue"))

    from src.mission_builder.puzzle_pipeline import is_puzzle_mission, build_puzzle_module
    if is_puzzle_mission(raw_type):
        return await build_puzzle_module(mission, _out_dir("Puzzle"))

    from src.mission_builder.investigation_pipeline import is_investigation_mission, build_investigation_module
    if is_investigation_mission(raw_type):
        return await build_investigation_module(mission, _out_dir("Investigation"))

    from src.mission_builder.negotiation_pipeline import is_negotiation_mission, build_negotiation_module
    if is_negotiation_mission(raw_type):
        return await build_negotiation_module(mission, _out_dir("Negotiation"))

    from src.mission_builder.first_contact_pipeline import is_first_contact_mission, build_first_contact_module
    if is_first_contact_mission(raw_type):
        return await build_first_contact_module(mission, _out_dir("First_Contact"))

    from src.mission_builder.discovery_pipeline import is_discovery_mission, build_discovery_module
    if is_discovery_mission(raw_type):
        return await build_discovery_module(mission, _out_dir("Discovery"))

    from src.mission_builder.exploration_pipeline import is_exploration_mission, build_exploration_module
    if is_exploration_mission(raw_type):
        return await build_exploration_module(mission, _out_dir("Exploration"))

    from src.mission_builder.strange_occurrences_pipeline import is_strange_occurrences_mission, build_strange_occurrences_module
    if is_strange_occurrences_mission(raw_type):
        return await build_strange_occurrences_module(mission, _out_dir("Strange_Occurrences"))

    from src.mission_builder.assassination_pipeline import is_assassination_mission, build_assassination_module
    if is_assassination_mission(raw_type):
        return await build_assassination_module(mission, _out_dir("Assassination"))

    # ── Legacy novel pipeline ────────────────────────────────────────────────
    if os.getenv("MODULE_PIPELINE", "published").lower() == "novel":
        from src.mission_builder.novel_pipeline import generate_novel_module
        return await generate_novel_module(mission, player_name)

    # ── Default: table-first published pipeline ──────────────────────────────
    from src.mission_builder.published_pipeline import generate_published_module
    return await generate_published_module(mission, player_name)


async def post_module_to_channel(client, index_path: Path, mission: dict, player_name: str) -> bool:
    """
    Post the generated novel module to the module output channel.

    index_path is the index.md inside the output directory.
    Posts: embed summary, all markdown files as attachments, then maps.
    """
    import discord

    channel_id = int(os.getenv("MODULE_OUTPUT_CHANNEL_ID", "0"))
    if not channel_id:
        logger.warning("MODULE_OUTPUT_CHANNEL_ID not set — cannot post module")
        return False

    channel = client.get_channel(channel_id)
    if not channel:
        logger.warning(f"Module output channel {channel_id} not found")
        return False

    title   = mission.get("title", "Unknown Mission")
    tier    = mission.get("tier", "standard").upper()
    cr      = get_cr(mission.get("tier", "standard"))
    faction = mission.get("faction", "Unknown")

    max_level  = get_max_pc_level()
    level_note = f" (party max level {max_level})" if max_level > 0 else ""

    # index_path is the index.md — parent is the output directory
    out_dir = index_path.parent if index_path.is_file() else index_path

    # Box set components only — chapters are novel context, not deliverables
    BOX_SET_SLUGS = ["dm_guide", "module", "players_guide", "chart_pack"]
    box_set_files = [out_dir / f"{s}.html" for s in BOX_SET_SLUGS if (out_dir / f"{s}.html").exists()]
    map_files     = sorted((out_dir / "maps").glob("*.png")) if (out_dir / "maps").is_dir() else []
    zip_path      = out_dir.parent / f"{out_dir.name}.zip"

    has_zip = zip_path.exists()
    zip_kb  = zip_path.stat().st_size // 1024 if has_zip else 0

    embed = discord.Embed(
        title=f"📖 Mission Module Ready: {title}",
        description=(
            f"**Claimed by:** {player_name}\n"
            f"**Faction:** {faction}\n"
            f"**Tier:** {tier} | **CR:** {cr}{level_note}\n"
            f"**Estimated Runtime:** ~4–5 hours\n\n"
            f"Box set: {len(box_set_files)} components · {len(map_files)} maps\n"
            + (f"📦 Full module ZIP attached ({zip_kb}KB)" if has_zip else "")
        ),
        color=discord.Color.dark_gold(),
    )
    embed.set_footer(text="Tower of Last Chance — Novel Pipeline | D&D 5e 2024")

    try:
        await channel.send(embed=embed)
        logger.info(f"Module embed posted to channel {channel_id}: {title}")

        # ZIP first — primary delivery artifact (novel chapters live in the zip, not posted separately)
        if has_zip and zip_path.stat().st_size < 25 * 1024 * 1024:
            await channel.send(
                content=(
                    f"📦 **Full Module ZIP** — `{zip_path.name}` ({zip_kb}KB)\n"
                    f"Contains: DM Guide, Module, Players Guide, Chart Pack, Maps + full novel chapters.\n"
                    f"Open any `.html` file in a browser for the styled module."
                ),
                file=discord.File(str(zip_path), filename=zip_path.name),
            )
            logger.info(f"✅ Module ZIP posted: {zip_path.name} ({zip_kb}KB)")
        elif has_zip:
            await channel.send(
                content=f"📦 Module ZIP ({zip_kb}KB) is too large for Discord. Server path: `{zip_path}`"
            )

        # Post box set components — DM Guide, Module, Players Guide, Chart Pack only
        # (no chapter files — they're novel context, not session deliverables)
        labels = {"dm_guide": "DM Guide", "module": "Module", "players_guide": "Players Guide", "chart_pack": "Chart Pack"}
        for f in box_set_files:
            slug = f.stem
            label = labels.get(slug, slug.replace("_", " ").title())
            await channel.send(
                content=f"📄 **{label}**",
                file=discord.File(str(f), filename=f.name),
            )
            logger.info(f"  → posted {label}")

        # Post maps (A1111-generated images from Pass 5)
        if map_files:
            for mp in map_files[:8]:
                await channel.send(
                    content=f"🗺️ **{mp.stem.replace('_', ' ').title()}**",
                    file=discord.File(str(mp), filename=mp.name),
                )
            logger.info(f"✅ {len(map_files)} maps posted for: {title}")

        # Also post DB-indexed maps for this mission
        try:
            from src.db_api import raw_query as _rq_maps
            map_rows = _rq_maps(
                "SELECT entity_name, image_path, metadata_json FROM image_refs"
                " WHERE entity_type = 'location_map'"
                " AND JSON_UNQUOTE(JSON_EXTRACT(metadata_json, '$.mission_title')) = %s"
                " ORDER BY id ASC",
                (title,),
            ) or []
            posted_paths = {str(m) for m in map_files}
            for row in map_rows:
                mp = Path(row["image_path"])
                if not mp.exists() or str(mp) in posted_paths:
                    continue
                meta     = row.get("metadata_json") or {}
                if isinstance(meta, str):
                    import json as _j
                    meta = _j.loads(meta)
                loc_type = meta.get("type", "")
                caption  = f"🗺️ **{row['entity_name']}**" + (f" — {loc_type}" if loc_type else "")
                await channel.send(content=caption, file=discord.File(str(mp), filename=mp.name))
        except Exception as e:
            logger.warning(f"DB map posting failed for {title}: {e}")

        return True
    except Exception as e:
        logger.error(f"Failed to post module: {e}")
        return False


# Convenience exports
__all__ = [
    "generate_module",
    "post_module_to_channel",
    "gather_context",
    "get_cr",
    "get_max_pc_level",
    "get_party_size",
    "get_output_dir",
    # Map generation
    "extract_map_scenes",
    "generate_vtt_map",
    "generate_module_maps",
    "post_maps_to_channel",
]
