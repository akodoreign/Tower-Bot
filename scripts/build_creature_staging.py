"""
build_creature_staging.py — Extract all custom creatures from generated modules
and write a DDB-ready staging JSON.

Sources (in order of richness):
  1. generated_modules/raw/RAW_*.md — full stat blocks with ability scores
  2. generated_modules/**/module.html — abbreviated inf-stat-block divs
  3. generated_modules/**/*.docx — parsed via python-docx (if available)

Output: scripts/creature_ddb_staging.json
        (same format as npc_ddb_staging.json — pass straight to import script)

Run from project root:
    python scripts/build_creature_staging.py
"""
from __future__ import annotations

import json, math, re, sys
from pathlib import Path
from typing import Optional

ROOT        = Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT / "generated_modules"
OUT_FILE    = ROOT / "scripts" / "creature_ddb_staging.json"
ART_DIR     = ROOT / "campaign_docs" / "npc_appearances" / "module_creatures_ddb"
ART_DIR.mkdir(parents=True, exist_ok=True)

HP_MULTIPLIER = 1.0   # module creatures keep standard HP (not boosted like NPCs)


# ── CR helpers ────────────────────────────────────────────────────────────────

CR_STR = {
    "0": 0, "1/8": 0.125, "1/4": 0.25, "1/2": 0.5,
    **{str(i): float(i) for i in range(1, 31)},
}

def parse_cr(s: str) -> float:
    s = str(s).strip()
    if "/" in s:
        a, b = s.split("/"); return float(a) / float(b)
    try: return float(s)
    except: return 1.0

def cr_to_str(cr: float) -> str:
    if cr < 0.25: return "1/8"
    if cr < 0.5:  return "1/4"
    if cr < 1.0:  return "1/2"
    return str(int(cr)) if cr == int(cr) else str(cr)

def cr_to_prof(cr: float) -> int:
    if cr <= 4:  return 2
    if cr <= 8:  return 3
    if cr <= 12: return 4
    if cr <= 16: return 5
    return 6

# ── Size/type normalisation ───────────────────────────────────────────────────

SIZE_MAP = {
    "tiny": "T", "small": "S", "medium": "M",
    "large": "L", "huge": "H", "gargantuan": "G",
}
TYPE_MAP = {
    "humanoid": "humanoid", "beast": "beast", "undead": "undead",
    "construct": "construct", "aberration": "aberration", "monstrosity": "monstrosity",
    "elemental": "elemental", "fey": "fey", "fiend": "fiend", "celestial": "celestial",
    "dragon": "dragon", "giant": "giant", "plant": "plant", "ooze": "ooze",
    "swarm": "humanoid",   # fallback
}

def norm_size(s: str) -> str:
    return SIZE_MAP.get(s.lower().strip(), "M")

def norm_type(s: str) -> str:
    sl = s.lower().strip()
    for k, v in TYPE_MAP.items():
        if k in sl:
            return v
    return "humanoid"

def hp_die_for_size(size: str) -> str:
    return {"T": "4", "S": "6", "M": "8", "L": "10", "H": "12", "G": "20"}.get(size, "8")


# ── CR-based ability score estimation ─────────────────────────────────────────
# Based on published_pipeline._stat_block formula

def estimate_scores(cr: float, creature_type: str) -> dict:
    icr = max(1, int(cr))
    if creature_type in ("beast", "plant", "ooze"):
        return {
            "STR": 14 + icr // 3, "DEX": 12 + icr // 4,
            "CON": 14 + icr // 3, "INT": 3, "WIS": 10, "CHA": 5,
        }
    elif creature_type in ("undead",):
        return {
            "STR": 12 + icr // 3, "DEX": 14 + icr // 4,
            "CON": 12 + icr // 3, "INT": 6, "WIS": 10, "CHA": 12,
        }
    elif creature_type in ("construct",):
        return {
            "STR": 16 + icr // 3, "DEX": 10, "CON": 16 + icr // 4,
            "INT": 10, "WIS": 10, "CHA": 5,
        }
    else:  # humanoid / monstrosity / default
        return {
            "STR": 12 + icr // 3, "DEX": 14 + icr // 4,
            "CON": 12 + icr // 3, "INT": 11, "WIS": 12, "CHA": 13,
        }


# ── Module speed parsing ──────────────────────────────────────────────────────

def parse_speed(speed_str: str) -> list:
    """Return list of (movement_type_id, ft) from a speed string like '30 ft., fly 60 ft.'"""
    TYPE_IDS = {"walk": 1, "burrow": 2, "climb": 3, "fly": 4, "swim": 5}
    speeds = []
    for part in (speed_str or "30 ft.").lower().split(","):
        part = part.strip()
        ft_match = re.search(r"(\d+)\s*ft", part)
        if not ft_match:
            continue
        ft = int(ft_match.group(1))
        type_id = 1  # walk default
        for k, v in TYPE_IDS.items():
            if k in part:
                type_id = v
                break
        if ft > 0:
            speeds.append((type_id, ft))
    return speeds or [(1, 30)]


# ── ─────────────────────────────────────────────────────────────────────────
# FORMAT 1: Parse RAW .md stat blocks
# Format: #### **Name** *(Size Type, Alignment)*
#         - **Armor Class** X
#         - **Hit Points** X (NdM + Y)
#         - **Speed** X ft.
#         - **STR** X (+Y) | **DEX** ...
#         - **Actions** / **Reactions** / **Traits** / etc.
# ─────────────────────────────────────────────────────────────────────────────

def _extract_md_section(block: str, section_keys: list[str]) -> str:
    """
    Extract abilities from a stat block section.

    Handles two formats:
      Grouped:  - **Traits**:\n  - **Name**: text
      Inline:   - **Reaction**: text   (single item on same line)
    """
    for key in section_keys:
        # Grouped format: "- **Section**:" followed by indented subitems
        pat_grouped = rf'(?m)^[ \t]*[-•][ \t]+\*\*{re.escape(key)}\*\*[^\n]*:\s*\n((?:[ \t]+[-•][ \t]+.+\n?)+)'
        m = re.search(pat_grouped, block, re.IGNORECASE)
        if m:
            lines = []
            for line in m.group(1).split('\n'):
                line = line.strip().lstrip('-• ').strip()
                line = re.sub(r'\*\*([^*]+)\*\*', r'\1', line)
                if line:
                    lines.append(line)
            if lines:
                return '\n\n'.join(lines)

        # Inline format: "- **Section**: text" (one item on same line)
        pat_inline = rf'(?m)^[ \t]*[-•][ \t]+\*\*{re.escape(key)}\*\*[^\n]*:\s+(.+)'
        m2 = re.search(pat_inline, block, re.IGNORECASE)
        if m2:
            text = re.sub(r'\*\*([^*]+)\*\*', r'\1', m2.group(1).strip())
            if text:
                return text

    return ''


def _extract_boss_traits(block: str) -> str:
    """
    Collect boss-style top-level trait bullets that have no grouped section header.
    Matches lines like:  - **Legendary Resistance** (1/Day): description
    """
    SKIP = {"traits", "special traits", "features", "actions", "action",
            "reactions", "reaction", "lair actions", "lair action",
            "legendary actions", "bonus actions"}
    lines = []
    for m in re.finditer(r'(?m)^[ \t]*[-•][ \t]+\*\*([^*\n]+)\*\*[^\n]*:\s+(.+)', block):
        key = m.group(1).strip().lower()
        if key not in SKIP:
            ability = re.sub(r'\*\*([^*]+)\*\*', r'\1', m.group(0).strip().lstrip('-• ').strip())
            lines.append(ability)
    return '\n\n'.join(lines)


def parse_md_stat_blocks(text: str) -> list[dict]:
    """Parse markdown stat blocks from RAW module files."""
    creatures = []
    blocks = re.split(r'\n(?=#{3,4}\s+\**[A-Z])', text)

    for block in blocks:
        name_m = re.match(
            r'#{3,4}\s+\**([^*\n(]+)\**\s*(?:\*\(([^)]+)\)\*)?', block.strip()
        )
        if not name_m:
            continue

        raw_name = name_m.group(1).strip().strip("*").strip()
        type_info = (name_m.group(2) or "").strip()

        # Actual format uses **AC** X and **HP** X (not Armor Class / Hit Points)
        ac_m = re.search(r'\*\*(?:AC|Armor Class)\*\*\s*(\d+)', block)
        hp_m = re.search(r'\*\*(?:HP|Hit Points)\*\*\s*(\d+)', block)
        if not ac_m or not hp_m:
            continue

        ac = int(ac_m.group(1))
        hp = int(hp_m.group(1))

        spd_m = re.search(r'\*\*Speed\*\*\s*([^\n]+)', block)
        speed_str = spd_m.group(1).strip() if spd_m else "30 ft."

        score_m = re.search(
            r'\*\*STR\*\*\s*(\d+).*?\*\*DEX\*\*\s*(\d+).*?\*\*CON\*\*\s*(\d+)'
            r'.*?\*\*INT\*\*\s*(\d+).*?\*\*WIS\*\*\s*(\d+).*?\*\*CHA\*\*\s*(\d+)',
            block, re.DOTALL
        )
        if score_m:
            str_s, dex_s, con_s, int_s, wis_s, cha_s = (int(x) for x in score_m.groups())
        else:
            scores = estimate_scores(1.0, "humanoid")
            str_s = scores["STR"]; dex_s = scores["DEX"]; con_s = scores["CON"]
            int_s = scores["INT"]; wis_s = scores["WIS"]; cha_s = scores["CHA"]

        cr_m = re.search(r'\*?\*?Challenge\*?\*?\s+(\d+/?\d*|[\d.]+)', block, re.IGNORECASE)
        cr   = parse_cr(cr_m.group(1)) if cr_m else 1.0

        hp_formula_m = re.search(r'\*\*(?:HP|Hit Points)\*\*\s*\d+\s*\((\d+)d(\d+)', block)
        hp_die_count = int(hp_formula_m.group(1)) if hp_formula_m else max(1, int(cr) or 1)
        hp_die       = hp_formula_m.group(2)       if hp_formula_m else "8"

        size_m = re.match(r'(tiny|small|medium|large|huge|gargantuan)', type_info, re.IGNORECASE)
        size   = norm_size(size_m.group(1) if size_m else "Medium")
        ctype  = norm_type(type_info)

        actions_text   = _extract_md_section(block, ["Actions", "Action"])
        traits_text    = _extract_md_section(block, ["Traits", "Special Traits", "Features"])
        reactions_text = _extract_md_section(block, ["Reactions", "Reaction"])
        legendary_text = _extract_md_section(block, ["Legendary Actions", "Legendary Action"])
        lair_text      = _extract_md_section(block, ["Lair Actions", "Lair Action"])

        # Boss creatures: collect top-level named abilities as traits when no grouped section
        if not traits_text:
            traits_text = _extract_boss_traits(block)

        pp = 10 + ((wis_s - 10) // 2) + cr_to_prof(cr)

        creatures.append({
            "name": raw_name, "cr": cr_to_str(cr), "creature_type": ctype,
            "size": size, "ac": ac, "hp": hp,
            "hp_die": hp_die, "hp_die_count": hp_die_count,
            "str_": str_s, "dex": dex_s, "con": con_s, "int_": int_s,
            "wis": wis_s, "cha": cha_s, "passive_perc": pp,
            "languages": "Common",
            "actions": actions_text, "traits": traits_text,
            "reactions": reactions_text, "bonus_actions": "",
            "legendary_actions": legendary_text, "mythic_actions": "",
            "lair_actions": lair_text,
            "notes": f"Generated for campaign module. {type_info}".strip(),
            "speeds": parse_speed(speed_str),
            "portrait_path": None, "sd_appearance": "",
            "saves": {}, "source": "raw_md",
        })

    return creatures


# ── ─────────────────────────────────────────────────────────────────────────
# FORMAT 2: Parse HTML module.html inf-stat-block divs
# Format: <div class="inf-stat-block"><b>Name</b> — CR X | HP Y | AC Z | 30 ft.
#         <div>⚔ Action text</div><div>★ Trait text</div></div>
# ─────────────────────────────────────────────────────────────────────────────

def _split_inf_stat_blocks(html: str) -> list[str]:
    """
    Split HTML into individual inf-stat-block inner contents.
    Uses a split-on-opening-tag approach so multiple inner <div>s are all captured.
    """
    marker = '<div class="inf-stat-block"'
    parts  = re.split(r'(?=<div class="inf-stat-block")', html)
    blocks = []
    for part in parts:
        if not part.lstrip().startswith(marker):
            continue
        # Strip the outer opening tag (up to first '>')
        gt = part.index('>')
        inner_with_tail = part[gt + 1:]
        # Everything up to (but not including) the outer closing </div>
        last_close = inner_with_tail.rfind('</div>')
        if last_close == -1:
            continue
        blocks.append(inner_with_tail[:last_close])
    return blocks


def parse_html_stat_blocks(html: str) -> list[dict]:
    """Parse inf-stat-block divs from module.html files."""
    creatures = []

    blocks = _split_inf_stat_blocks(html)

    for block in blocks:
        # Name
        name_m = re.search(r'<b>(?:👑\s*)?([^<]+)</b>', block)
        if not name_m:
            continue
        raw_name = name_m.group(1).strip()
        # Remove emoji/crown
        raw_name = re.sub(r'^[👑🗡️🧟‍♂️⚔🛡️]+\s*', '', raw_name).strip()
        if not raw_name:
            continue

        # Header line: Name — CR X | HP Y | AC Z | speed
        header_m = re.search(
            r'</b>\s*[—-]\s*CR\s*([\d/]+)\s*\|\s*HP\s*(\d+)\s*\|\s*AC\s*(\d+)\s*\|([^<\n]+)',
            block, re.IGNORECASE
        )
        if not header_m:
            continue

        cr_s   = header_m.group(1).strip()
        hp     = int(header_m.group(2))
        ac     = int(header_m.group(3))
        spd_raw= header_m.group(4).strip()

        cr = parse_cr(cr_s)

        # Actions (⚔) and traits (★) and lair (🗺️)
        sub_divs = re.findall(r'<div>(.*?)</div>', block, re.DOTALL)
        actions_lines  = []
        traits_lines   = []
        lair_lines     = []

        for div in sub_divs:
            clean = re.sub(r'<[^>]+>', '', div).strip()
            if not clean:
                continue
            if clean.startswith("⚔"):
                actions_lines.append(clean[1:].strip())
            elif clean.startswith("★"):
                traits_lines.append(clean[1:].strip())
            elif clean.startswith("🗺"):
                lair_lines.append(clean[2:].strip())
            elif clean.startswith("🎯"):
                pass  # tactics — skip
            else:
                # Generic div — might be extra trait or action
                if any(w in clean.lower() for w in ("attack:", "saving throw", "recharge", "dc ")):
                    actions_lines.append(clean)
                elif clean:
                    traits_lines.append(clean)

        # Estimate ability scores from CR
        scores  = estimate_scores(cr, "humanoid")
        str_s   = scores["STR"]; dex_s = scores["DEX"]; con_s = scores["CON"]
        int_s   = scores["INT"]; wis_s = scores["WIS"]; cha_s = scores["CHA"]

        size    = "M"  # HTML format doesn't include size — default Medium
        ctype   = "humanoid"  # default
        hp_die  = hp_die_for_size(size)
        pb      = cr_to_prof(cr)
        hp_die_count = max(1, round(hp / (int(hp_die)/2 + 0.5 + (con_s-10)//2)))
        pp      = 10 + (wis_s - 10) // 2 + pb

        creatures.append({
            "name":          raw_name,
            "cr":            cr_to_str(cr),
            "creature_type": ctype,
            "size":          size,
            "ac":            ac,
            "hp":            hp,
            "hp_die":        hp_die,
            "hp_die_count":  hp_die_count,
            "str_":  str_s, "dex": dex_s, "con": con_s,
            "int_":  int_s, "wis": wis_s, "cha": cha_s,
            "passive_perc":  pp,
            "languages":     "Common",
            "actions":       "\n\n".join(actions_lines),
            "traits":        "\n\n".join(traits_lines),
            "reactions":     "",
            "bonus_actions": "",
            "legendary_actions": "",
            "mythic_actions": "",
            "lair_actions":  "\n\n".join(lair_lines),
            "notes":         "Generated creature from module encounter.",
            "speeds":        parse_speed(spd_raw),
            "portrait_path": None, "sd_appearance": "",
            "saves":         {}, "source": "module_html",
        })

    return creatures


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    # Load NPC names already queued — skip duplicates
    npc_staging = ROOT / "scripts" / "npc_ddb_staging.json"
    npc_names: set[str] = set()
    if npc_staging.exists():
        try:
            for entry in json.loads(npc_staging.read_text(encoding="utf-8")):
                npc_names.add(entry.get("name", "").strip())
            print(f"Loaded {len(npc_names)} NPC names to skip (dedup)")
        except Exception as exc:
            print(f"  WARN: could not load NPC staging: {exc}")

    all_creatures: dict[str, dict] = {}  # name → creature dict

    # 1. RAW MD files — richest data
    print("Parsing RAW .md files...")
    for f in sorted((MODULES_DIR / "raw").glob("RAW_*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            found = parse_md_stat_blocks(text)
            for c in found:
                nm = c["name"]
                if nm not in all_creatures and nm not in npc_names:
                    all_creatures[nm] = c
                    all_creatures[nm]["source_file"] = str(f.name)
        except Exception as exc:
            print(f"  WARN {f.name}: {exc}")
    print(f"  After MD: {len(all_creatures)} unique creatures")

    # 2. module.html files — broader coverage
    print("Parsing module.html files...")
    for f in sorted(MODULES_DIR.rglob("module.html")):
        try:
            html = f.read_text(encoding="utf-8", errors="ignore")
            found = parse_html_stat_blocks(html)
            for c in found:
                nm = c["name"]
                if nm not in all_creatures and nm not in npc_names:
                    all_creatures[nm] = c
                    all_creatures[nm]["source_file"] = str(f.parent.name + "/module.html")
        except Exception as exc:
            print(f"  WARN {f.parent.name}: {exc}")
    print(f"  After HTML: {len(all_creatures)} unique creatures")

    # 3. Also try chapter HTML files for the newer module format
    print("Parsing chapter*.html files...")
    for f in sorted(MODULES_DIR.rglob("chapter_*.html")):
        try:
            html = f.read_text(encoding="utf-8", errors="ignore")
            found = parse_html_stat_blocks(html)
            for c in found:
                nm = c["name"]
                if nm not in all_creatures and nm not in npc_names:
                    all_creatures[nm] = c
                    all_creatures[nm]["source_file"] = str(f.parent.name + "/" + f.name)
        except Exception as exc:
            print(f"  WARN {f.name}: {exc}")
    print(f"  After chapters: {len(all_creatures)} unique creatures")

    # Filter: must have at least one action
    valid = {nm: c for nm, c in all_creatures.items() if c.get("actions") or c.get("traits")}
    print(f"\nValid (have actions/traits): {len(valid)}")

    # Summary
    from collections import Counter
    sources = Counter(c["source"] for c in valid.values())
    print(f"By source: {dict(sources)}")
    cr_dist = Counter(c["cr"] for c in valid.values())
    print(f"CR distribution: {dict(sorted(cr_dist.items(), key=lambda x: parse_cr(x[0])))}")

    # Sample
    for nm, c in list(valid.items())[:2]:
        print(f"\n=== {nm} CR{c['cr']} {c['creature_type']} ===")
        print(f"  AC {c['ac']} HP {c['hp']} | STR {c['str_']} DEX {c['dex']}")
        print(f"  Actions: {c['actions'][:120]}...")
        print(f"  Traits:  {c['traits'][:80]}...")
        print(f"  Source:  {c.get('source_file')}")

    result = list(valid.values())
    OUT_FILE.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    print(f"\nStaging file: {OUT_FILE}")
    print(f"Total: {len(result)} creatures ready for DDB import")


if __name__ == "__main__":
    main()
