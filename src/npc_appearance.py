"""
npc_appearance.py — Generate and store rich appearance/style/stat profiles for all NPCs.

For each NPC in npc_roster.json, generates:
  - Physical appearance (from existing roster field, enhanced)
  - Class + estimated stats appropriate to their role
  - Equipment appropriate to class/faction/role
  - Style description for Stable Diffusion (based on race, class, faction aesthetic)

Stored in: campaign_docs/npc_appearances/{name_slug}.json
Also maintains a quick-lookup flat file for image prompt injection.

Usage:
  python -m src.npc_appearance   (run once to generate all)
  from src.npc_appearance import get_npc_appearance, get_npc_sd_prompt
"""

from __future__ import annotations

import json
import re
import os
import asyncio
from pathlib import Path
from typing import Optional

from src.log import logger

DOCS_DIR         = Path(__file__).resolve().parent.parent / "campaign_docs"
NPC_ROSTER_FILE  = DOCS_DIR / "npc_roster.json"
NPC_APP_DIR      = DOCS_DIR / "npc_appearances"
NPC_APP_DIR.mkdir(exist_ok=True)

# ─── Race-based physical baselines ──────────────────────────────────────────

RACE_PHYSIQUE = {
    "human":      "average height and build for a human; unremarkable at a glance",
    "half-elf":   "slightly taller than human, with subtly pointed ears and a graceful build",
    "elf":        "tall, lithe, with sharply pointed ears and an ageless quality to their face",
    "dwarf":      "stocky and broad-shouldered, roughly 4.5 feet tall with dense muscle",
    "halfling":   "barely 3 feet tall, light on their feet, with large expressive eyes",
    "gnome":      "small even for a halfling, wiry and quick, eyes perpetually alert",
    "half-orc":   "taller than most humans, heavily muscled with visible tusks and greenish skin tone",
    "orc":        "massive frame, deep green or grey skin, prominent tusks, built like a siege weapon",
    "tiefling":   "humanoid with small horns, a long tail, and skin in shades of red, violet, or grey",
    "aasimar":    "radiant skin that catches light oddly, often with faint golden or silver undertones",
    "dragonborn": "scaled humanoid standing over 6 feet, with a draconic head and tail",
    "goblin":     "barely 3 feet, large bat-like ears, wide eyes, wiry and hunched",
    "kobold":     "small reptilian humanoid, about 2.5 feet, with a long snout and scaly skin",
    "unknown":    "their exact heritage is unclear — something in the way they move suggests it isn't entirely human",
}

# ─── Class → combat role, stat priority, weapon, armour ────────────────────

CLASS_PROFILES = {
    "fighter": {
        "role":      "frontline warrior",
        "primary":   ["STR 16", "CON 15", "DEX 13"],
        "secondary": ["WIS 11", "INT 10", "CHA 9"],
        "hp_range":  "52–68",
        "weapons":   "longsword or hand axe, shield",
        "armour":    "chain mail or scale mail",
        "style_note": "built for impact — armour is well-maintained and personalised with notches or markings",
    },
    "arcane archer": {
        "role":      "ranged magical fighter",
        "primary":   ["DEX 16", "STR 14", "INT 13"],
        "secondary": ["CON 12", "WIS 11", "CHA 9"],
        "hp_range":  "48–60",
        "weapons":   "longbow, shortsword",
        "armour":    "studded leather",
        "style_note": "hunter's precision — everything positioned for the shot, quiver always accessible",
    },
    "rogue": {
        "role":      "infiltrator and scout",
        "primary":   ["DEX 17", "CHA 14", "INT 13"],
        "secondary": ["CON 12", "WIS 10", "STR 9"],
        "hp_range":  "35–50",
        "weapons":   "twin daggers or rapier, hand crossbow",
        "armour":    "dark leather armour",
        "style_note": "dark layered clothing, nothing that catches light, pockets everywhere, soft-soled boots",
    },
    "wizard": {
        "role":      "arcane spellcaster",
        "primary":   ["INT 17", "DEX 14", "CON 13"],
        "secondary": ["WIS 11", "CHA 10", "STR 8"],
        "hp_range":  "28–42",
        "weapons":   "staff or wand, dagger at the belt",
        "armour":    "robes (no armour)",
        "style_note": "heavy robe with component pockets, often ink-stained, sometimes accidentally burned",
    },
    "cleric": {
        "role":      "divine healer and support",
        "primary":   ["WIS 17", "CON 14", "STR 13"],
        "secondary": ["CHA 12", "INT 10", "DEX 9"],
        "hp_range":  "45–60",
        "weapons":   "mace or warhammer, holy symbol",
        "armour":    "chain mail, shield",
        "style_note": "divine symbolism is prominent — their god's motif woven in or worn as jewellery",
    },
    "ranger": {
        "role":      "tracker and archer",
        "primary":   ["DEX 16", "WIS 14", "STR 13"],
        "secondary": ["CON 12", "INT 10", "CHA 9"],
        "hp_range":  "45–60",
        "weapons":   "longbow, shortsword",
        "armour":    "studded leather, travel cloak",
        "style_note": "earth tones, multiple layers, weather-adapted — looks like they've been outside for weeks",
    },
    "paladin": {
        "role":      "divine warrior",
        "primary":   ["STR 16", "CHA 15", "CON 14"],
        "secondary": ["WIS 11", "INT 10", "DEX 9"],
        "hp_range":  "55–72",
        "weapons":   "longsword or warhammer, holy symbol",
        "armour":    "plate armour, shield",
        "style_note": "armour polished to a standard, divine marks clearly visible — presence intended",
    },
    "barbarian": {
        "role":      "rage-fuelled melee",
        "primary":   ["STR 18", "CON 16", "DEX 12"],
        "secondary": ["WIS 11", "INT 8", "CHA 9"],
        "hp_range":  "65–85",
        "weapons":   "greataxe or maul",
        "armour":    "hide armour or none",
        "style_note": "minimal clothing, what's there chosen for freedom of movement and intimidation",
    },
    "bard": {
        "role":      "support and face",
        "primary":   ["CHA 17", "DEX 14", "INT 13"],
        "secondary": ["CON 12", "WIS 10", "STR 9"],
        "hp_range":  "38–52",
        "weapons":   "rapier, hand crossbow or instrument",
        "armour":    "leather armour",
        "style_note": "expressive and colourful, crafted to draw eyes — changes frequently",
    },
    "warlock": {
        "role":      "pact-powered caster",
        "primary":   ["CHA 17", "CON 14", "DEX 13"],
        "secondary": ["INT 12", "WIS 10", "STR 8"],
        "hp_range":  "40–55",
        "weapons":   "eldritched pact weapon, dagger",
        "armour":    "leather armour",
        "style_note": "patron's influence bleeds through — subtle wrongness in the cut or material",
    },
    "druid": {
        "role":      "nature spellcaster",
        "primary":   ["WIS 17", "CON 14", "DEX 12"],
        "secondary": ["INT 11", "CHA 10", "STR 9"],
        "hp_range":  "40–55",
        "weapons":   "staff, scimitar, sickle",
        "armour":    "hide or leather (no metal), wooden shield",
        "style_note": "natural materials, sometimes still growing — the Undercity version uses Rift-flora",
    },
    "monk": {
        "role":      "unarmed martial artist",
        "primary":   ["DEX 17", "WIS 15", "CON 13"],
        "secondary": ["STR 12", "INT 10", "CHA 8"],
        "hp_range":  "45–60",
        "weapons":   "shortsword, unarmed strikes",
        "armour":    "no armour (unarmoured defense)",
        "style_note": "stripped down, nothing unnecessary — what's there is perfect quality",
    },
    "sorcerer": {
        "role":      "innate spellcaster",
        "primary":   ["CHA 17", "CON 14", "DEX 13"],
        "secondary": ["INT 11", "WIS 10", "STR 8"],
        "hp_range":  "35–48",
        "weapons":   "quarterstaff or dagger",
        "armour":    "no armour (mage armour)",
        "style_note": "clothing that reacts to their power — sparks, frost, or shadows at the hem",
    },
    "artificer": {
        "role":      "inventor and gadgeteer",
        "primary":   ["INT 17", "CON 14", "DEX 13"],
        "secondary": ["WIS 11", "CHA 10", "STR 9"],
        "hp_range":  "40–55",
        "weapons":   "hand crossbow, tools as weapons",
        "armour":    "medium armour with tool harness",
        "style_note": "tool harnesses, component belts, goggles, at least one thing that ticks or glows",
    },
    "blood hunter": {
        "role":      "monster-hunting warrior",
        "primary":   ["STR 16", "DEX 14", "CON 13"],
        "secondary": ["INT 12", "WIS 10", "CHA 9"],
        "hp_range":  "48–65",
        "weapons":   "martial weapon, hand crossbow",
        "armour":    "studded leather or chain mail",
        "style_note": "scarred, dark, the smell of alchemical reagents — clothing shows the cost of the power",
    },
    # Non-class roles — estimate by faction role
    "senior acquisitions agent": {
        "role":      "field agent and broker",
        "primary":   ["CHA 16", "DEX 14", "INT 13"],
        "secondary": ["WIS 12", "CON 11", "STR 9"],
        "hp_range":  "35–50",
        "weapons":   "concealed blade, crossbow",
        "armour":    "fine coat over leather",
        "style_note": "mercantile-military — expensive but practical, always armed, never obviously so",
    },
    "inspector": {
        "role":      "investigator",
        "primary":   ["INT 16", "WIS 14", "CHA 13"],
        "secondary": ["DEX 12", "CON 11", "STR 9"],
        "hp_range":  "30–42",
        "weapons":   "concealed short sword, crossbow",
        "armour":    "civilian clothes, padded vest under coat",
        "style_note": "civilian, unremarkable by design — carrying a ledger and looking exhausted",
    },
    "information broker": {
        "role":      "social operative",
        "primary":   ["CHA 16", "INT 15", "DEX 14"],
        "secondary": ["WIS 13", "CON 10", "STR 8"],
        "hp_range":  "28–40",
        "weapons":   "hidden dagger",
        "armour":    "elegant street clothes with hidden pockets",
        "style_note": "always different outfit — never the same twice, always appropriate to the situation",
    },
    "archivist": {
        "role":      "scholar and researcher",
        "primary":   ["INT 17", "WIS 14", "CHA 10"],
        "secondary": ["DEX 12", "CON 11", "STR 8"],
        "hp_range":  "25–38",
        "weapons":   "staff or dagger (last resort)",
        "armour":    "scholar's robes",
        "style_note": "ink-stained hands, reading lenses, reinforced elbows, multiple scroll cases",
    },
    "memory architect": {
        "role":      "specialist psychic operative",
        "primary":   ["INT 17", "CHA 14", "WIS 13"],
        "secondary": ["DEX 12", "CON 10", "STR 8"],
        "hp_range":  "28–40",
        "weapons":   "concealed knife, memory vials",
        "armour":    "fine black clothing, always gloved",
        "style_note": "quiet in a way that feels engineered — black-on-black with glass-bead accessories",
    },
    "contract mediator": {
        "role":      "divine negotiator",
        "primary":   ["CHA 17", "WIS 15", "INT 14"],
        "secondary": ["CON 12", "DEX 10", "STR 8"],
        "hp_range":  "28–40",
        "weapons":   "none visible (contract seals are weapons enough)",
        "armour":    "formal divine robes",
        "style_note": "formal at all times, contract sigils embroidered at cuffs, no wasted movement",
    },
    "field captain": {
        "role":      "veteran fighter",
        "primary":   ["STR 16", "CON 15", "WIS 13"],
        "secondary": ["DEX 12", "CHA 10", "INT 9"],
        "hp_range":  "55–72",
        "weapons":   "battle axe, heavy crossbow",
        "armour":    "patchwork plate — heavily repaired, still effective",
        "style_note": "repaired many times with love, red armband the only consistent mark",
    },
    "speaker": {
        "role":      "cult orator and organiser",
        "primary":   ["CHA 16", "WIS 13", "INT 12"],
        "secondary": ["CON 11", "DEX 10", "STR 8"],
        "hp_range":  "25–38",
        "weapons":   "makeshift staff, hidden dagger",
        "armour":    "tattered cult robes",
        "style_note": "cult's grey wrappings, makeshift metal-banded staff, fervent expression",
    },
    "senior blade": {
        "role":      "veteran arena fighter",
        "primary":   ["STR 16", "DEX 14", "CON 14"],
        "secondary": ["CHA 12", "WIS 10", "INT 9"],
        "hp_range":  "55–70",
        "weapons":   "longsword, shield with faction emblem",
        "armour":    "polished scale mail or plate",
        "style_note": "theatrical glory-hunter — everything designed to be seen from the stands",
    },
    "warden": {
        "role":      "city defender",
        "primary":   ["CON 15", "STR 14", "WIS 12"],
        "secondary": ["DEX 11", "CHA 10", "INT 9"],
        "hp_range":  "45–60",
        "weapons":   "spear, crossbow, handaxe",
        "armour":    "chain mail, Warden badge",
        "style_note": "utilitarian-military — built to survive, nothing wasted",
    },
    "officer": {
        "role":      "military commander",
        "primary":   ["STR 15", "CON 14", "WIS 13"],
        "secondary": ["CHA 12", "DEX 11", "INT 10"],
        "hp_range":  "55–72",
        "weapons":   "longsword, heavy crossbow",
        "armour":    "plate armour, officer's insignia",
        "style_note": "armour maintained to standard, rank markings clearly displayed",
    },
    "compliance officer": {
        "role":      "bureaucratic enforcer",
        "primary":   ["INT 15", "WIS 13", "CHA 12"],
        "secondary": ["DEX 11", "CON 10", "STR 9"],
        "hp_range":  "28–38",
        "weapons":   "short sword, FTA badge",
        "armour":    "FTA uniform over light armour",
        "style_note": "FTA uniform kept immaculate — young, earnest, slightly too eager",
    },
    "acolyte": {
        "role":      "religious operative",
        "primary":   ["WIS 14", "CHA 13", "INT 12"],
        "secondary": ["CON 11", "DEX 10", "STR 9"],
        "hp_range":  "25–35",
        "weapons":   "mace, holy symbol",
        "armour":    "vestments, light padding",
        "style_note": "faction's divine colours, symbol prominently displayed",
    },
    "contract scribe": {
        "role":      "legal operative",
        "primary":   ["INT 16", "CHA 14", "WIS 12"],
        "secondary": ["DEX 11", "CON 10", "STR 8"],
        "hp_range":  "22–35",
        "weapons":   "quill as a weapon (metaphorically), dagger",
        "armour":    "tattered coat over threadbare robe",
        "style_note": "coat over robe, always quill and parchment, forked tongue flickering",
    },
    "mercenary": {
        "role":      "hired fighter",
        "primary":   ["STR 15", "CON 14", "DEX 13"],
        "secondary": ["WIS 11", "CHA 10", "INT 9"],
        "hp_range":  "45–60",
        "weapons":   "warhammer, crossbow",
        "armour":    "chain mail or scale mail",
        "style_note": "worn leather and chainmail, equipment that tells a story of past contracts",
    },
    "street runner": {
        "role":      "courier and scout",
        "primary":   ["DEX 16", "CHA 13", "INT 12"],
        "secondary": ["CON 11", "WIS 10", "STR 9"],
        "hp_range":  "28–40",
        "weapons":   "daggers, sling",
        "armour":    "leather coat",
        "style_note": "practical street clothes, nothing that slows movement, worn boots",
    },
    "freelance": {
        "role":      "independent operative",
        "primary":   ["varies by specialty"],
        "secondary": ["varies"],
        "hp_range":  "35–55",
        "weapons":   "varied — chosen for the job",
        "armour":    "practical adventuring gear",
        "style_note": "eclectic — no faction marks, which is itself a statement",
    },
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip())


def _race_key(species: str) -> str:
    s = species.lower()
    for key in RACE_PHYSIQUE:
        if key in s:
            return key
    return "unknown"


def _class_key(rank: str) -> str:
    """Map an NPC rank/role string to the closest CLASS_PROFILES key."""
    r = rank.lower()
    # Direct matches first
    for key in CLASS_PROFILES:
        if key in r:
            return key
    # Fuzzy fallbacks
    if "blade" in r:        return "senior blade"
    if "warden" in r:       return "warden"
    if "inspector" in r:    return "inspector"
    if "agent" in r:        return "senior acquisitions agent"
    if "broker" in r:       return "information broker"
    if "archivist" in r:    return "archivist"
    if "scribe" in r:       return "contract scribe"
    if "mediator" in r:     return "contract mediator"
    if "compliance" in r:   return "compliance officer"
    if "runner" in r:       return "street runner"
    if "speaker" in r:      return "speaker"
    if "acolyte" in r:      return "acolyte"
    if "captain" in r:      return "field captain"
    if "officer" in r:      return "officer"
    if "architect" in r:    return "memory architect"
    if "sergeant" in r:     return "warden"
    if "mercenary" in r or "freelance" in r or "prospect" in r: return "freelance"
    return "mercenary"  # safe fallback — fighter-type


def _faction_key(faction: str) -> str:
    f = faction.lower()
    if "iron fang" in f:    return "iron_fang"
    if "argent" in f:       return "argent_blades"
    if "warden" in f:       return "wardens_of_ash"
    if "serpent" in f:      return "serpent_choir"
    if "obsidian" in f:     return "obsidian_lotus"
    if "glass sigil" in f:  return "glass_sigil"
    if "patchwork" in f:    return "patchwork_saints"
    if "adventurer" in f:   return "adventurers_guild"
    if "ashen scroll" in f: return "ashen_scrolls"
    if "tower" in f or "fta" in f: return "adventurers_guild"
    if "thane" in f or "cult" in f: return "independent"
    return "independent"


# Faction visual notes for SD prompt (condensed from style_agent.py)
FACTION_SD_NOTES = {
    "iron_fang":        "deep burgundy and gunmetal coat, Iron Fang mark subtle on lapel, always armed",
    "argent_blades":    "silver and white armour with blue accents, arena medals, theatrical presence",
    "wardens_of_ash":   "ash grey chainmail or plate, Warden badge, ash-mark on left cheek if officer",
    "serpent_choir":    "jade green and black divine silk robes, coiled serpent motif, contract seals as pendants",
    "obsidian_lotus":   "black shadow-woven clothing, lotus flower motifs in black glass, memory vials as jewellery",
    "glass_sigil":      "pale blue scholar robes, brass instrument clips, glass-lens goggles, ink-stained hands",
    "patchwork_saints":  "patchwork cloth of many fabrics, red armband, worn-but-loved boots, medicinal pouch",
    "adventurers_guild": "rank-appropriate gear from leather to enchanted plate, Guild badge displayed",
    "ashen_scrolls":    "ash-white archival robes, multiple sealed scroll cases, fate-reading tools",
    "independent":      "eclectic mix, deliberately no faction marks, one defining personal item",
}


async def _generate_npc_profile(npc: dict) -> dict:
    """Generate a full appearance, stats, equipment, and SD style profile for one NPC."""
    from src.style_agent import FACTION_STYLE_NOTES

    name      = npc.get("name", "Unknown")
    species   = npc.get("species", "Human")
    faction   = npc.get("faction", "Independent")
    rank      = npc.get("rank", "")
    appearance = npc.get("appearance", "")
    motivation = npc.get("motivation", "")
    role       = npc.get("role", "")

    race_key    = _race_key(species)
    class_key   = _class_key(rank)
    faction_key = _faction_key(faction)

    race_note    = RACE_PHYSIQUE.get(race_key, RACE_PHYSIQUE["unknown"])
    class_prof   = CLASS_PROFILES.get(class_key, CLASS_PROFILES["mercenary"])
    faction_vis  = FACTION_SD_NOTES.get(faction_key, FACTION_SD_NOTES["independent"])

    # Ask Ollama to write the enriched style description
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    prompt = f"""You are writing a visual character profile for an Undercity NPC. 
The Undercity is a dark sealed fantasy city containing fashion, materials, and people from all devoured worlds.
Write in the style of a Stable Diffusion image prompt: specific, vivid, tactile, no generic fantasy descriptions.

CHARACTER:
Name: {name}
Species: {species} — {race_note}
Faction: {faction}
Role/Rank: {rank}
Known appearance: {appearance}
Role summary: {role}
Motivation hint: {motivation}

FACTION VISUAL STYLE: {faction_vis}
CLASS/ROLE EQUIPMENT: {class_prof['weapons']}, wearing {class_prof['armour']}
CLASS STYLE NOTE: {class_prof['style_note']}

Write a SINGLE PARAGRAPH (3-4 sentences) describing this NPC as they would appear in a scene.
Include: build/height from species, skin/hair/eye details, outfit (faction-appropriate), equipment visible on their person, one distinctive visual detail.
Output ONLY the paragraph. No names, no preamble, no sign-off. Written as SD prompt phrases."""

    import httpx
    sd_description = ""
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                sd_description = msg.get("content", "").strip()

        lines = sd_description.splitlines()
        skip  = ("sure", "here's", "here is", "certainly", "of course", "below is")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        sd_description = " ".join(l.strip() for l in lines if l.strip())

    except Exception as e:
        logger.warning(f"NPC profile generation failed for {name}: {e}")
        sd_description = (
            f"{species}, {appearance}, wearing {class_prof['armour']}, "
            f"carrying {class_prof['weapons']}, {faction_vis}"
        )

    home_district = _location_to_district_key(npc.get("location", ""))

    profile = {
        "name":          name,
        "species":       species,
        "faction":       faction,
        "rank":          rank,
        "role":          class_key,
        "home_district": home_district,
        "stats":         {
            "primary":   class_prof["primary"],
            "secondary": class_prof["secondary"],
            "hp_range":  class_prof["hp_range"],
        },
        "equipment": {
            "weapons":   class_prof["weapons"],
            "armour":    class_prof["armour"],
        },
        "sd_appearance": sd_description,
        "faction_visual": faction_vis,
        "style_note":    class_prof["style_note"],
    }
    return profile


def _profile_path(name: str) -> Path:
    return NPC_APP_DIR / f"{_slug(name)}.json"


def get_npc_appearance(name: str) -> Optional[dict]:
    """Load a stored NPC appearance profile. Returns None if not yet generated."""
    p = _profile_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_npc_sd_prompt(name: str) -> Optional[str]:
    """Get just the SD-ready appearance description for an NPC."""
    profile = get_npc_appearance(name)
    if not profile:
        return None
    return profile.get("sd_appearance")


def get_all_npc_names() -> list[str]:
    """Return all NPC names from the roster."""
    if not NPC_ROSTER_FILE.exists():
        return []
    try:
        roster = json.loads(NPC_ROSTER_FILE.read_text(encoding="utf-8"))
        return [npc.get("name", "") for npc in roster if npc.get("name")]
    except Exception:
        return []


async def generate_all_npc_appearances(force: bool = False) -> dict[str, str]:
    """
    Generate and store appearance profiles for all NPCs in the roster.
    Skips NPCs that already have a stored profile unless force=True.
    Returns {name: sd_appearance} for all processed NPCs.
    """
    if not NPC_ROSTER_FILE.exists():
        logger.warning("npc_roster.json not found")
        return {}

    roster = json.loads(NPC_ROSTER_FILE.read_text(encoding="utf-8"))
    results = {}

    for npc in roster:
        name = npc.get("name", "")
        if not name:
            continue

        p = _profile_path(name)
        if p.exists() and not force:
            # Load existing
            try:
                existing = json.loads(p.read_text(encoding="utf-8"))
                results[name] = existing.get("sd_appearance", "")
                logger.info(f"✓ Loaded existing profile: {name}")
                continue
            except Exception:
                pass

        logger.info(f"⚙ Generating appearance for: {name}")
        try:
            profile = await _generate_npc_profile(npc)
            p.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
            results[name] = profile.get("sd_appearance", "")
            logger.info(f"✓ Saved profile: {name}")
        except Exception as e:
            logger.error(f"✗ Failed to generate profile for {name}: {e}")
            results[name] = npc.get("appearance", "")

        # Small delay to not hammer Ollama
        await asyncio.sleep(2)

    # Also write a flat lookup JSON for quick image prompt access
    flat_path = NPC_APP_DIR / "_all_sd_prompts.json"
    flat_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"💾 Saved flat SD prompt lookup: {flat_path}")

    return results


def get_all_sd_prompts() -> dict[str, str]:
    """Load the flat {name: sd_prompt} lookup. Returns {} if not yet generated."""
    flat_path = NPC_APP_DIR / "_all_sd_prompts.json"
    if not flat_path.exists():
        return {}
    try:
        return json.loads(flat_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ─── NPC home location → district key mapping ───────────────────────────────
# Maps keywords found in the NPC roster's free-text `location` field to the
# canonical district keys used in _DISTRICT_AESTHETICS in news_feed.py.
# Ordered most-specific first so longer phrases match before shorter ones.

_LOCATION_KEYWORD_MAP: list[tuple[list[str], str]] = [
    (["crimson alley"],                          "crimson alley"),
    (["neon row"],                               "neon row"),
    (["cobbleway"],                              "cobbleway market"),
    (["floating bazaar"],                        "floating bazaar"),
    (["taste of worlds"],                        "taste of worlds"),
    (["grand forum library"],                    "grand forum library"),
    (["fountain of echoes"],                     "fountain of echoes"),
    (["rift bulletin"],                          "rift bulletin board"),
    (["adventurer's inn", "adventurers inn"],    "adventurer's inn"),
    (["adventurers guild", "adventurer guild"],  "adventurers guild"),
    (["grand forum", "forum district"],          "grand forum"),
    (["glass sigil", "catacombs"],               "glass sigil"),
    (["arena of ascendance"],                    "arena of ascendance"),
    (["argent blades", "cryptwards",
      "iron quarter", "mourning quarter"],        "argent blades"),
    (["silver spire"],                           "silver spire"),
    (["serpent choir spire"],                    "serpent choir spire"),
    (["ashen scrolls", "scriptorium",
      "archival depths"],                        "ashen scrolls tower"),
    (["guild spires", "lament's spire",
      "lament spire", "shattered spire",
      "citadel district", "downtower"],           "guild spires"),
    (["pantheon walk"],                          "pantheon walk"),
    (["divine garden"],                          "divine garden"),
    (["hall of echoes"],                         "hall of echoes"),
    (["sanctum", "temple quarter",
      "ash mansion"],                            "sanctum quarter"),
    (["shantytown heights", "shantytown"],       "shantytown heights"),
    (["scrapworks", "forge district"],           "scrapworks"),
    (["brother thane", "cathedral"],             "brother thane"),
    (["night pits"],                             "night pits"),
    (["echo alley"],                             "echo alley"),
    (["collapsed plaza"],                        "collapsed plaza"),
    (["patchwork saints"],                       "patchwork saints"),
    (["obsidian lotus"],                         "obsidian lotus"),
    (["iron fang"],                              "iron fang"),
    (["outer wall", "wall quadrant",
      "checkpoint", "ash wastes",
      "ashen hollow", "the citadel",
      "citadel, the"],                           "outer wall"),
    (["warrens", "midden", "lower undercity",
      "dockyards", "rust alley",
      "lower dockyards"],                        "warrens"),
    (["markets infinite", "markets"],            "markets infinite"),
]


def _location_to_district_key(location_text: str) -> str:
    """
    Convert a free-text NPC `location` string to the canonical district key
    used in _DISTRICT_AESTHETICS. Returns empty string if no match.
    """
    loc = location_text.lower()
    for keywords, district_key in _LOCATION_KEYWORD_MAP:
        if any(kw in loc for kw in keywords):
            return district_key
    return ""


def get_npc_home_district(name: str) -> str:
    """
    Return the district key for where this NPC lives/works.
    Checks stored appearance profile first, then falls back to the roster.
    Returns empty string if nothing can be determined.
    """
    # 1. Try stored profile (fast path, already computed)
    profile = get_npc_appearance(name)
    if profile and profile.get("home_district"):
        return profile["home_district"]

    # 2. Fall back to roster location field
    if not NPC_ROSTER_FILE.exists():
        return ""
    try:
        roster = json.loads(NPC_ROSTER_FILE.read_text(encoding="utf-8"))
        for npc in roster:
            if npc.get("name", "").lower() == name.lower():
                loc = npc.get("location", "")
                return _location_to_district_key(loc)
    except Exception:
        pass
    return ""


def find_npc_in_text(text: str) -> list[tuple[str, str, str]]:
    """
    Scan text for NPC names.
    Returns list of (name, sd_prompt, home_district_key) for every NPC found.
    home_district_key matches the keys in news_feed._DISTRICT_AESTHETICS.
    """
    sd_prompts = get_all_sd_prompts()
    found = []
    text_lower = text.lower()
    for name, prompt in sd_prompts.items():
        first = name.split()[0].lower()
        if name.lower() in text_lower or first in text_lower:
            home = get_npc_home_district(name)
            found.append((name, prompt, home))
    return found


# ─── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    force = "--force" in sys.argv
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    loop = asyncio.new_event_loop()
    results = loop.run_until_complete(generate_all_npc_appearances(force=force))
    print(f"\n✅ Generated {len(results)} NPC appearance profiles")
    for name, desc in results.items():
        print(f"\n[{name}]\n  {desc[:120]}...")
