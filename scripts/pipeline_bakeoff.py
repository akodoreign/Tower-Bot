"""Run repeated mission pipeline builds and score diversity/playability.

This is an audit harness, not production code. It generates temporary module
outputs under generated_modules/pipeline_bakeoff_* and writes a Markdown report.

Usage:
  python scripts/pipeline_bakeoff.py --runs 3
  python scripts/pipeline_bakeoff.py --runs 2 --types ambush heist rescue
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Keep this harness from reaching out through optional Mimir paths.
# Maps stay enabled by default because current mission maps are library downloads,
# not on-the-spot image generation.
os.environ.setdefault("MODULE_GENERATE_MAPS", "true")
os.environ["MIMIR_MCP_PATH"] = ""
os.environ.setdefault("OPENAI_ENABLED", "false")


TYPE_MISSIONS: dict[str, dict] = {
    "ambush": {
        "title": "Briar Gate Intercept",
        "type": "Ambush",
        "mission_type": "ambush",
        "faction": "Wardens of Ash",
        "opposing_faction": "Iron Fang Consortium",
        "tier": "standard",
        "difficulty": 5,
        "primary_location": "Outer Wall freight gate",
        "body": "Stop an Iron Fang courier convoy before it carries stolen watch sigils through the Outer Wall freight gate.",
    },
    "assassination": {
        "title": "The Widow's Quiet Mark",
        "type": "Assassination",
        "mission_type": "assassination",
        "faction": "Obsidian Lotus",
        "opposing_faction": "Serpent Choir",
        "tier": "high-stakes",
        "difficulty": 7,
        "primary_location": "Sanctum Quarter reliquary annex",
        "body": "Neutralize a Choir contract-broker whose divine writ has started naming Lotus safehouse owners.",
    },
    "assault": {
        "title": "Storm the Iron Tithe House",
        "type": "Assault",
        "mission_type": "assault",
        "faction": "Patchwork Saints",
        "opposing_faction": "Iron Fang Consortium",
        "tier": "major",
        "difficulty": 6,
        "primary_location": "Scrapworks tithe house",
        "body": "Lead a push into an Iron Fang tithe house and seize the ledger vault before the defenders burn the records.",
    },
    "battle": {
        "title": "Forum Line Break",
        "type": "Battle",
        "mission_type": "battle",
        "faction": "Tower Authority / FTA",
        "opposing_faction": "Brother Thane's Cult",
        "tier": "major",
        "difficulty": 6,
        "primary_location": "Grand Forum barricades",
        "body": "Break a cult-backed street battle around the Grand Forum barricades before the public hearing collapses into bloodshed.",
    },
    "defense": {
        "title": "Hold the Ash Gate",
        "type": "Defense",
        "mission_type": "defense",
        "faction": "Wardens of Ash",
        "opposing_faction": "Obsidian Lotus",
        "tier": "major",
        "difficulty": 6,
        "primary_location": "Ash Gate checkpoint",
        "body": "Defend the Ash Gate checkpoint while informants evacuate through the back tunnels.",
    },
    "discovery": {
        "title": "Signal Under Glass",
        "type": "Discovery",
        "mission_type": "discovery",
        "faction": "Glass Sigil",
        "opposing_faction": "None",
        "tier": "investigation",
        "difficulty": 5,
        "primary_location": "Archive Row sealed study",
        "body": "Identify and contain a singing crystal signal that records memories of people who have not arrived yet.",
    },
    "escort": {
        "title": "The Sealed Reliquary Walk",
        "type": "Escort",
        "mission_type": "escort",
        "faction": "Serpent Choir",
        "opposing_faction": "Obsidian Lotus",
        "tier": "standard",
        "difficulty": 4,
        "primary_location": "Sanctum Quarter to Markets Infinite",
        "body": "Escort a sealed reliquary and its nervous junior priest through watched market routes.",
    },
    "exploration": {
        "title": "Survey the Replaced Stair",
        "type": "Exploration",
        "mission_type": "exploration",
        "faction": "Adventurers Guild",
        "opposing_faction": "None",
        "tier": "investigation",
        "difficulty": 5,
        "primary_location": "The Warrens replaced stairwell",
        "body": "Map a stairwell that now descends into a district nobody remembers building.",
    },
    "first_contact": {
        "title": "The People From the Blue Orchard",
        "type": "First Contact",
        "mission_type": "first contact",
        "faction": "Tower Authority / FTA",
        "opposing_faction": "Iron Fang Consortium",
        "tier": "investigation",
        "difficulty": 4,
        "primary_location": "Outer Wall arrival shelter",
        "body": "Protect and communicate with newly arrived orchard-folk before factions turn them into a resource fight.",
    },
    "gathering": {
        "title": "Three Reagents Before Dawn",
        "type": "Gathering",
        "mission_type": "gathering",
        "faction": "Wizards Tower",
        "opposing_faction": "None",
        "tier": "standard",
        "difficulty": 4,
        "primary_location": "Markets Infinite reagent lanes",
        "body": "Collect three unstable reagents from different sellers before a containment ritual begins at dawn.",
    },
    "heist": {
        "title": "The Mirror Ledger Job",
        "type": "Heist",
        "mission_type": "heist",
        "faction": "Obsidian Lotus",
        "opposing_faction": "Iron Fang Consortium",
        "tier": "high-stakes",
        "difficulty": 7,
        "primary_location": "Iron Fang counting house",
        "body": "Steal or swap a mirror ledger from an Iron Fang counting house during a crowded auction night.",
    },
    "infestation": {
        "title": "Cellar Teeth Bloom",
        "type": "Infestation",
        "mission_type": "infestation",
        "faction": "Patchwork Saints",
        "opposing_faction": "None",
        "tier": "standard",
        "difficulty": 5,
        "primary_location": "Warrens cellar tunnels",
        "body": "Clear a spreading cellar infestation before it reaches sleeping tenements above.",
    },
    "infiltration": {
        "title": "False Badge at Archive Row",
        "type": "Infiltration",
        "mission_type": "infiltration",
        "faction": "Glass Sigil",
        "opposing_faction": "Tower Authority / FTA",
        "tier": "high-stakes",
        "difficulty": 7,
        "primary_location": "Tower Authority records annex",
        "body": "Enter the records annex under false credentials and copy a sealed hearing transcript.",
    },
    "investigation": {
        "title": "The Witness Who Died Twice",
        "type": "Investigation",
        "mission_type": "investigation",
        "faction": "Guild of Ashen Scrolls",
        "opposing_faction": "Brother Thane's Cult",
        "tier": "investigation",
        "difficulty": 5,
        "primary_location": "Grand Forum witness dormitory",
        "body": "Find out why a protected witness has two death records and one active room assignment.",
    },
    "negotiation": {
        "title": "Terms for the Broken Bridge",
        "type": "Negotiation",
        "mission_type": "negotiation",
        "faction": "Adventurers Guild",
        "opposing_faction": "Wardens of Ash",
        "tier": "investigation",
        "difficulty": 4,
        "primary_location": "Grand Forum neutral chamber",
        "body": "Broker terms between Guild runners and Wardens after a bridge checkpoint beating went public.",
    },
    "puzzle": {
        "title": "The Graffiti Sequence",
        "type": "Puzzle",
        "mission_type": "puzzle",
        "faction": "Guild of Ashen Scrolls",
        "opposing_faction": "None",
        "tier": "investigation",
        "difficulty": 5,
        "primary_location": "Markets Infinite mural wall",
        "body": "Decode a public graffiti sequence before someone paints over the missing final symbol.",
    },
    "recovery": {
        "title": "Recover the Misdelivered Heartbox",
        "type": "Recovery",
        "mission_type": "recovery",
        "faction": "Adventurers Guild",
        "opposing_faction": "Obsidian Lotus",
        "tier": "standard",
        "difficulty": 4,
        "primary_location": "Markets Infinite parcel exchange",
        "body": "Recover a misdelivered heartbox before the wrong recipient opens it and starts a faction panic.",
    },
    "rescue": {
        "title": "Extract the Bellwright",
        "type": "Rescue",
        "mission_type": "rescue",
        "faction": "Patchwork Saints",
        "opposing_faction": "Iron Fang Consortium",
        "tier": "standard",
        "difficulty": 5,
        "primary_location": "Scrapworks bell foundry",
        "body": "Extract a trapped bellwright from a foundry locked down by debt collectors.",
    },
    "sabotage": {
        "title": "Silence the Counting Engine",
        "type": "Sabotage",
        "mission_type": "sabotage",
        "faction": "Obsidian Lotus",
        "opposing_faction": "Iron Fang Consortium",
        "tier": "high-stakes",
        "difficulty": 7,
        "primary_location": "Iron Fang counting engine room",
        "body": "Disable the counting engine long enough for forged debt records to become impossible to verify.",
    },
    "strange_occurrences": {
        "title": "The Dead Clerk's Second Shift",
        "type": "Strange Occurrences",
        "mission_type": "strange occurrences",
        "faction": "Serpent Choir",
        "opposing_faction": "None",
        "tier": "investigation",
        "difficulty": 5,
        "primary_location": "Grand Forum permit office",
        "body": "Investigate why a dead clerk is calmly working a second shift and stamping permits with tomorrow's date.",
    },
    # Board/fallback/alias mission types beyond the 20 dedicated pipeline labels.
    "bounty": {
        "title": "The Warrant in Rust Alley",
        "type": "Bounty Hunt",
        "mission_type": "bounty hunt",
        "faction": "Wardens of Ash",
        "tier": "standard",
        "difficulty": 5,
        "primary_location": "Rust Alley",
        "body": "A wanted deserter has gone to ground in Rust Alley with stolen Warden records and a crew of desperate friends.",
    },
    "delivery": {
        "title": "The Sealed Blue Satchel",
        "type": "Courier / Delivery",
        "mission_type": "delivery",
        "faction": "Glass Sigil",
        "tier": "standard",
        "difficulty": 4,
        "primary_location": "district boundary checkpoints",
        "body": "Carry a sealed satchel across district lines during a watch rotation without opening it or letting rivals confirm it exists.",
    },
    "dungeon": {
        "title": "The Vault Under Soot Market",
        "type": "Dungeon Delve",
        "mission_type": "dungeon delve",
        "faction": "Adventurers Guild",
        "tier": "hard",
        "difficulty": 7,
        "primary_location": "Soot Market cellar vault",
        "body": "A collapsed market cellar has opened into a sealed pre-Tower vault, and something inside has started scraping at the stone.",
    },
    "epic": {
        "title": "The Bell That Rings Above Weather",
        "type": "Epic / Divine Mission",
        "mission_type": "epic divine mission",
        "faction": "Tower Authority / FTA",
        "tier": "epic",
        "difficulty": 10,
        "primary_location": "upper Tower bell chamber",
        "body": "A divine bell on an upper floor has begun ringing names before disasters happen, and the next name belongs to the city itself.",
    },
    "espionage": {
        "title": "The Rival Ledger Room",
        "type": "Faction Espionage",
        "mission_type": "espionage",
        "faction": "Glass Sigil",
        "tier": "standard",
        "difficulty": 6,
        "primary_location": "rival records office",
        "body": "Enter a rival records office under false pretense, copy the meeting ledger, and leave without proving the Glass Sigil was involved.",
    },
    "high_stakes": {
        "title": "The Treaty Knife",
        "type": "High-Stakes Contract",
        "mission_type": "high-stakes contract",
        "faction": "Obsidian Lotus",
        "tier": "major",
        "difficulty": 8,
        "primary_location": "private treaty ceremony",
        "body": "A treaty signing will move three factions at once; recover, expose, or eliminate the leverage hidden inside the ceremony.",
    },
    "inter_guild": {
        "title": "The Guildhall Pressure Vote",
        "type": "Inter-Guild Conflict",
        "mission_type": "inter-guild conflict",
        "faction": "Adventurers Guild",
        "tier": "standard",
        "difficulty": 6,
        "primary_location": "Adventurers Guild hall",
        "body": "Two guild blocs are preparing to sabotage a vote; uncover the move, stop it quietly, or broker terms before the hall splits.",
    },
    "neighbourhood": {
        "title": "The Lantern Tax on Larkspur Row",
        "type": "Neighbourhood Job",
        "mission_type": "neighbourhood job",
        "faction": "Adventurers Guild",
        "tier": "standard",
        "difficulty": 3,
        "primary_location": "Larkspur Row",
        "body": "A street-level protection racket is squeezing Larkspur Row, and locals need it solved without turning the block into a battlefield.",
    },
    "patrol": {
        "title": "The South Stair Patrol",
        "type": "Patrol Contract",
        "mission_type": "patrol contract",
        "faction": "Wardens of Ash",
        "tier": "standard",
        "difficulty": 4,
        "primary_location": "South Stair circuit",
        "body": "Walk the South Stair circuit after three watch crews report hearing the same voice from different locked doors.",
    },
    "political": {
        "title": "The Blackmail Seat",
        "type": "Political Intrigue",
        "mission_type": "political intrigue",
        "faction": "Glass Sigil",
        "tier": "standard",
        "difficulty": 6,
        "primary_location": "private council antechamber",
        "body": "A council seat is being bought with blackmail; secure the proof, protect the asset, and avoid making the patron look desperate.",
    },
    "protection": {
        "title": "Keep Mari Fen Alive",
        "type": "Protection Detail",
        "mission_type": "protection detail",
        "faction": "Adventurers Guild",
        "tier": "standard",
        "difficulty": 5,
        "primary_location": "public testimony route",
        "body": "A witness must attend two public appointments and survive the day while someone tests the party's security from the crowd.",
    },
    "rift": {
        "title": "The Guttervein Rift Clearance",
        "type": "Rift Clearance",
        "mission_type": "rift clearance",
        "faction": "Wardens of Ash",
        "tier": "hard",
        "difficulty": 7,
        "primary_location": "Guttervein rift site",
        "body": "A small rift in the Guttervein is breathing heat into nearby rooms, and the last cleanup crew returned speaking in an unknown language.",
    },
    "smuggling": {
        "title": "The Quiet Crate Run",
        "type": "Smuggling Run",
        "mission_type": "smuggling run",
        "faction": "Iron Fang Consortium",
        "tier": "standard",
        "difficulty": 5,
        "primary_location": "inspection cordon",
        "body": "Move a crate of unregistered relic parts through a tightening inspection cordon without burning the route or naming the sponsor.",
    },
    "theft": {
        "title": "The Amber Key Theft",
        "type": "Theft / Heist",
        "mission_type": "theft heist",
        "faction": "Obsidian Lotus",
        "tier": "standard",
        "difficulty": 6,
        "primary_location": "guarded auction display",
        "body": "Steal the Amber Key from a guarded auction display, swap in a convincing fake, and leave before the owner knows the bidding was cover.",
    },
}


@dataclass
class RunResult:
    pipeline: str
    run: int
    ok: bool
    out_dir: str
    error: str
    title: str
    chars: int
    words: int
    headings: int
    checks: int
    tables: int
    forms: int
    maps: int
    vtt: int
    maps_page: bool
    linked_maps: bool
    none_hits: int
    placeholder_hits: int
    score: float
    text_sample: str


def clean_text(text: str) -> str:
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def tokens(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_'-]{2,}", text.lower())
        if t not in {
            "the",
            "and",
            "for",
            "with",
            "mission",
            "module",
            "guide",
            "session",
            "players",
            "player",
            "faction",
            "tower",
            "table",
        }
    }


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / max(1, len(a | b))


def _diversity_signals(out_dir: Path) -> set[str]:
    """
    Build a set of high-signal distinguishing tokens for one bakeoff run.

    Sources:
      1. VTT sidecars → district, map_type, location_name, library_map_id (stamped at copy time)
      2. clean_text(module.html) tokens from content-only prose (LLM-generated)

    Deliberately excludes generic structural terms so Jaccard measures content
    diversity, not template similarity.
    """
    signals: set[str] = set()

    # 1. VTT sidecars — district, map_type, location slug, and library_map_id are
    #    strongly run-specific. library_map_id is stamped by copy_library_map_for_mission.
    import json
    for vtt in sorted(out_dir.rglob("*.vtt.json")):
        try:
            ctx = json.loads(vtt.read_text(encoding="utf-8", errors="ignore")).get("context", {})
            for field in ("district", "map_type", "location_name", "area"):
                val = str(ctx.get(field) or "").strip().lower()
                if val:
                    signals.update(re.findall(r"[a-z]{3,}", val))
            lib_id = ctx.get("library_map_id")
            if lib_id:
                signals.add(f"mapid_{lib_id}")
            lib_mt = ctx.get("library_map_type")
            if lib_mt:
                signals.add(f"maptype_{lib_mt}")
        except Exception:
            pass

    # 3. Content words from module.html — LLM-generated prose differs per run
    mod = out_dir / "module.html"
    if mod.exists():
        prose = clean_text(mod.read_text(encoding="utf-8", errors="replace"))[:5000]
        content_tokens = {
            t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_'-]{3,}", prose.lower())
            if t not in {
                "the", "and", "for", "with", "mission", "module", "guide", "session",
                "players", "player", "faction", "tower", "table", "this", "that",
                "their", "they", "from", "have", "will", "been", "each", "also",
                "note", "notes", "strong", "style", "border", "color", "width",
                "check", "result", "success", "failure", "round", "scene", "lead",
            }
        }
        signals.update(content_tokens)

    return signals


def read_all_html(out_dir: Path) -> tuple[str, str]:
    parts = []
    main = ""
    for name in ("index.html", "module.html", "session.html", "dm_guide.html", "players_guide.html", "chart_pack.html", "maps.html"):
        p = out_dir / name
        if p.exists():
            raw = p.read_text(encoding="utf-8", errors="replace")
            if name in ("module.html", "session.html"):
                main += "\n" + raw
            parts.append(raw)
    return "\n".join(parts), main or "\n".join(parts)


def score_output(pipeline: str, out_dir: Path) -> RunResult:
    raw, main = read_all_html(out_dir)
    text = clean_text(main)
    all_text = clean_text(raw)
    headings = len(re.findall(r"<h[1-4]\b", raw, flags=re.I))
    checks = raw.count("checkbox")
    tables = len(re.findall(r"<table\b", raw, flags=re.I))
    forms = len(re.findall(r"<textarea\b|<input\b|<select\b", raw, flags=re.I))
    maps = len(list(out_dir.rglob("*.png"))) + len(list(out_dir.rglob("*.jpg"))) + len(list(out_dir.rglob("*.webp")))
    vtt = len(list(out_dir.rglob("*.vtt.json")))
    maps_page = (out_dir / "maps.html").exists()
    linked_maps = bool(re.search(r"maps\.html|<img\b", raw, flags=re.I))
    # Strip known-good phrases before scanning to avoid false positives
    _none_scan = re.sub(r'\bNone expected\b', '', all_text, flags=re.I)
    none_hits = len(re.findall(r"\bNone\b|null|Unknown Faction", _none_scan))
    # Strip HTML attribute values before scanning so placeholder= attrs don't false-positive
    _scan_text = re.sub(r'\bplaceholder\s*=\s*["\'][^"\']*["\']', '', all_text)
    placeholder_hits = len(re.findall(r"Test [1-5]\b|\bplaceholder\b|TODO\b|(?<!\w)unnamed\b|generic fallback|someone who can be negotiated", _scan_text, re.I))

    # Lightweight playability heuristic. Diversity is computed across runs.
    score = 0.0
    score += min(2.0, headings / 5.0)
    score += min(1.5, checks / 8.0)
    score += min(1.0, tables / 4.0)
    score += min(1.0, forms / 5.0)
    score += 1.0 if (out_dir / "session.html").exists() else 0.0
    score += 0.75 if (out_dir / "dm_guide.html").exists() else 0.0
    score += 0.75 if (out_dir / "players_guide.html").exists() else 0.0
    score += 0.75 if (out_dir / "chart_pack.html").exists() else 0.0
    score += 0.75 if maps else 0.0
    score += 0.50 if maps_page else 0.0
    score += 0.50 if linked_maps else 0.0
    if maps and not maps_page:
        score -= 0.75
    if maps and not vtt:
        score -= 0.50
    score -= min(2.0, none_hits * 0.35 + placeholder_hits * 0.25)
    score = max(0.0, min(10.0, score))

    title_match = re.search(r"<title>(.*?)</title>", raw, re.I | re.S)
    title = clean_text(title_match.group(1)) if title_match else out_dir.name

    return RunResult(
        pipeline=pipeline,
        run=0,
        ok=True,
        out_dir=str(out_dir),
        error="",
        title=title,
        chars=len(all_text),
        words=len(all_text.split()),
        headings=headings,
        checks=checks,
        tables=tables,
        forms=forms,
        maps=maps,
        vtt=vtt,
        maps_page=maps_page,
        linked_maps=linked_maps,
        none_hits=none_hits,
        placeholder_hits=placeholder_hits,
        score=round(score, 2),
        text_sample=all_text[:350],
    )


async def build_one(pipeline: str, run_num: int, batch_dir: Path) -> RunResult:
    from src.mission_builder import generate_module

    mission = dict(TYPE_MISSIONS[pipeline])
    mission["id"] = 990000 + run_num
    mission["title"] = f"{mission['title']} Bakeoff {run_num}"
    mission["bakeoff_run"] = run_num

    before = {p.resolve() for p in (ROOT / "generated_modules").glob("*") if p.is_dir()}
    try:
        path = await generate_module(mission, player_name="Bakeoff Party")
        if not path or not Path(path).exists():
            raise RuntimeError("generate_module returned no path")
        out_dir = Path(path).parent
        dest = batch_dir / out_dir.name
        if out_dir.resolve() != dest.resolve():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.move(str(out_dir), str(dest))
            zip_path = out_dir.with_suffix(".zip")
            if zip_path.exists():
                shutil.move(str(zip_path), str(batch_dir / zip_path.name))
            out_dir = dest
        result = score_output(pipeline, out_dir)
        result.run = run_num
        return result
    except Exception as exc:
        # Best effort: identify any newly created output dir.
        after = {p.resolve() for p in (ROOT / "generated_modules").glob("*") if p.is_dir()}
        new_dirs = sorted(after - before, key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return RunResult(
            pipeline=pipeline,
            run=run_num,
            ok=False,
            out_dir=str(new_dirs[0]) if new_dirs else "",
            error=f"{type(exc).__name__}: {exc}",
            title="",
            chars=0,
            words=0,
            headings=0,
            checks=0,
            tables=0,
            forms=0,
            maps=0,
            vtt=0,
            maps_page=False,
            linked_maps=False,
            none_hits=0,
            placeholder_hits=0,
            score=0.0,
            text_sample="",
        )


def summarize(results: list[RunResult], report_path: Path, runs: int) -> None:
    lines: list[str] = []
    lines.append("# Pipeline Bakeoff Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Runs per pipeline requested:** {runs}")
    lines.append(f"**Outputs:** `{report_path.parent.relative_to(ROOT)}`")
    lines.append("")
    lines.append("Maps are enabled. Scores include module HTML structure, session usability, internal variety, obvious broken placeholders, and map delivery artifacts.")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append("| Pipeline | Runs OK | Playability Avg | Uniqueness | Red Flags | Notes |")
    lines.append("|---|---:|---:|---:|---:|---|")

    by_pipeline: dict[str, list[RunResult]] = {}
    for r in results:
        by_pipeline.setdefault(r.pipeline, []).append(r)

    for pipeline in sorted(by_pipeline):
        rows = by_pipeline[pipeline]
        ok = [r for r in rows if r.ok]
        avg = statistics.mean([r.score for r in ok]) if ok else 0.0
        token_sets = [
            _diversity_signals(Path(r.out_dir))
            if r.ok
            else tokens(r.text_sample)
            for r in ok
        ]
        sims = []
        for i in range(len(token_sets)):
            for j in range(i + 1, len(token_sets)):
                sims.append(jaccard(token_sets[i], token_sets[j]))
        uniqueness = 10.0 if not sims else max(0.0, 10.0 * (1.0 - statistics.mean(sims)))
        red = sum(r.none_hits + r.placeholder_hits for r in ok) + sum(1 for r in rows if not r.ok) * 5
        note_bits = []
        if any(not r.ok for r in rows):
            note_bits.append("build failures")
        if ok and sum(r.maps for r in ok) == 0:
            note_bits.append("no maps copied")
        if ok and any(r.maps and not r.maps_page for r in ok):
            note_bits.append("maps not linked")
        if ok and any(r.maps and not r.vtt for r in ok):
            note_bits.append("maps lack VTT sidecars")
        if ok and sum(r.forms + r.checks for r in ok) == 0:
            note_bits.append("few table controls")
        if red:
            note_bits.append("placeholder/None leakage")
        lines.append(
            f"| {pipeline} | {len(ok)}/{len(rows)} | {avg:.1f} | {uniqueness:.1f} | {red} | {', '.join(note_bits) or 'clean'} |"
        )

    lines.append("")
    lines.append("## Run Details")
    lines.append("")
    for pipeline in sorted(by_pipeline):
        lines.append(f"### {pipeline}")
        lines.append("")
        lines.append("| Run | OK | Score | Words | Hdg | Checks | Tables | Forms | Maps | VTT | Maps Page | Linked | None | Placeholders | Output |")
        lines.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---:|---|")
        for r in by_pipeline[pipeline]:
            rel = ""
            if r.out_dir:
                try:
                    rel = str(Path(r.out_dir).relative_to(ROOT))
                except Exception:
                    rel = r.out_dir
            lines.append(
                f"| {r.run} | {'yes' if r.ok else 'NO'} | {r.score:.1f} | {r.words} | {r.headings} | {r.checks} | {r.tables} | {r.forms} | {r.maps} | {r.vtt} | {'yes' if r.maps_page else 'no'} | {'yes' if r.linked_maps else 'no'} | {r.none_hits} | {r.placeholder_hits} | `{rel}` |"
            )
            if r.error:
                lines.append(f"|  |  |  |  |  |  |  |  |  |  |  |  | ERROR: {r.error} |")
        lines.append("")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--types", nargs="*", default=[])
    args = parser.parse_args()

    selected = args.types or sorted(TYPE_MISSIONS)
    missing = [t for t in selected if t not in TYPE_MISSIONS]
    if missing:
        raise SystemExit(f"Unknown pipeline type(s): {', '.join(missing)}")

    batch_dir = ROOT / "generated_modules" / f"pipeline_bakeoff_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_dir.mkdir(parents=True, exist_ok=True)
    results: list[RunResult] = []

    for pipeline in selected:
        print(f"\n=== {pipeline} ===")
        for run in range(1, args.runs + 1):
            print(f"  run {run}/{args.runs}...", flush=True)
            result = await build_one(pipeline, run, batch_dir)
            results.append(result)
            if result.ok:
                print(f"    OK score={result.score} words={result.words} out={Path(result.out_dir).name}")
            else:
                print(f"    FAIL {result.error}")

    report_path = batch_dir / "pipeline_bakeoff_report.md"
    summarize(results, report_path, args.runs)
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    asyncio.run(main())
