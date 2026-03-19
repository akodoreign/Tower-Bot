"""
style_agent.py — Style, clothing, and appearance agent for Tower of Last Chance.

Two purposes:
  1. Player-facing /style command — "what would my character wear to X?"
     Given a character name/class/faction and occasion, returns a vivid
     description of outfit, colours, materials, and accessories.

  2. Internal use — enrich /draw prompts and /setcharappearance descriptions
     with clothing details appropriate to the character and Undercity setting.

The Undercity aesthetic:
  - Architecture and fashion from ALL worlds the Tower has devoured.
  - Dark, worn, practical base — topped with faction-specific flourishes.
  - Materials range from medieval cloth to salvaged tech to divine silk.
  - Lighting is mostly artificial: torch, bioluminescent vials, neon enchantment.

Exported:
    describe_character_style(char_name, char_class, faction, occasion, context) -> str
    enrich_appearance_prompt(base_description, char_class, faction) -> str
    FACTION_STYLE_NOTES  — dict for reference
"""

from __future__ import annotations

import os
from typing import Optional

from src.log import logger


# ---------------------------------------------------------------------------
# Faction aesthetic profiles
# Used to ground clothing descriptions in faction identity.
# ---------------------------------------------------------------------------

FACTION_STYLE_NOTES = {
    "iron_fang": {
        "name": "Iron Fang Consortium",
        "palette": "deep burgundy, gunmetal grey, tarnished gold",
        "materials": "studded leather, reinforced canvas, salvaged metal plate",
        "accessories": "carved relic fragments as jewellery, ledger pouches, hidden blade sheaths",
        "vibe": "mercantile-military: wealthy but practical, always armed, never ostentatious",
        "signature": "the Iron Fang mark — a stylised fang — somewhere on clothing, often subtle",
    },
    "argent_blades": {
        "name": "Argent Blades",
        "palette": "silver, white, electric blue accents",
        "materials": "polished scale mail, fine white linen, enchanted cloth that doesn't stain",
        "accessories": "arena medals, sponsor badges, signet rings, hero's sash",
        "vibe": "theatrical glory-hunter: everything is meant to be seen from the stands",
        "signature": "silver trim that catches light, deliberate visual impact",
    },
    "wardens_of_ash": {
        "name": "Wardens of Ash",
        "palette": "ash grey, black, iron, with rare blood-red accents for officers",
        "materials": "heavy wool, chainmail, plate armour, oiled leather",
        "accessories": "Warden badge, ash-mark on the cheek (ceremonial), torch-holder belt clips",
        "vibe": "utilitarian-military: built to survive, nothing wasted, everything worn",
        "signature": "the ash smear — three fingers dragged across the left cheek for officers",
    },
    "serpent_choir": {
        "name": "Serpent Choir",
        "palette": "deep jade green, black, gold, with divine white for high-ranking clergy",
        "materials": "divine silk (impossibly smooth), written-on parchment sewn into lining, snakeskin trim",
        "accessories": "contract seals worn as pendants, coiled serpent motifs, quill and inkwell as belt items",
        "vibe": "priestly-bureaucratic: every garment implies authority and hidden clauses",
        "signature": "a visible serpent motif, and clothing that seems to fit too perfectly",
    },
    "obsidian_lotus": {
        "name": "Obsidian Lotus",
        "palette": "black, deep violet, with flashes of iridescent oil-slick colour",
        "materials": "shadow-woven cloth (light doesn't reflect normally), glass bead accents, void-touched leather",
        "accessories": "memory vials worn as jewellery, lotus flower motifs in black glass, hidden pockets everywhere",
        "vibe": "elegant-sinister: designed to make you forget you saw them, but impossible to ignore",
        "signature": "clothing that seems to shift colour slightly in peripheral vision",
    },
    "glass_sigil": {
        "name": "Glass Sigil",
        "palette": "pale blue, white, silver, with faint luminescent yellow for active instruments",
        "materials": "scholar's robes, reinforced at the elbows, instrument-harness straps, glass-lens goggles",
        "accessories": "brass instrument clips, anomaly charts folded in pockets, calibration tools",
        "vibe": "academic-arcane: functional and slightly dishevelled, everything has a purpose",
        "signature": "at least one glass instrument visibly worn, plus ink-stained fingers",
    },
    "patchwork_saints": {
        "name": "Patchwork Saints",
        "palette": "no consistent palette — literally patchwork: whatever was available",
        "materials": "repaired and re-repaired cloth, multiple layers, mismatched fabrics all carefully maintained",
        "accessories": "red cloth armband (their only consistent mark), medicinal pouch, worn boots resoled many times",
        "vibe": "humble-heroic: dressed like they lost everything and kept going anyway",
        "signature": "the red armband, and clothes that have clearly been mended with love",
    },
    "adventurers_guild": {
        "name": "Adventurers' Guild",
        "palette": "varies by rank — E/D grey-brown, C rank leather tan, B rank dark blue, A rank deep crimson, S rank black-gold",
        "materials": "practical adventuring gear scaled to rank — leather at low ranks, enchanted materials at high",
        "accessories": "Guild rank badge prominently displayed, contract pouch, rank-appropriate weapon",
        "vibe": "practical-aspirational: dressed to survive, but rank markings everywhere",
        "signature": "Guild rank badge, and equipment that tells a story of past contracts",
    },
    "ashen_scrolls": {
        "name": "Guild of Ashen Scrolls",
        "palette": "ash white, faded black, old parchment yellow",
        "materials": "archival robes, scroll-case bandoliers, treated cloth that resists decay",
        "accessories": "multiple scroll cases, fate-reading tools, a worn copy of a personal archive",
        "vibe": "withdrawn-scholarly: dressed as if they expect to be forgotten, which they prefer",
        "signature": "a personal sealed scroll case always on the person",
    },
    "independent": {
        "name": "Independent",
        "palette": "whatever they can afford or steal",
        "materials": "mixed — independence shows in eclectic choices",
        "accessories": "varies wildly — often a defining object that tells their backstory",
        "vibe": "no faction rules: dress reflects personality more than affiliation",
        "signature": "deliberate absence of faction markings, which is itself a statement",
    },
}

# Class-based style modifiers
CLASS_STYLE_NOTES = {
    "fighter":     "practical and durable — armour is well-maintained and personalised with notches or markings",
    "rogue":       "dark, layered, nothing that catches light — pockets everywhere, soft-soled boots",
    "wizard":      "heavy robe with component pockets, often ink-stained, sometimes accidentally burned",
    "cleric":      "divine symbolism is prominent — their god's motif woven in or worn as jewellery",
    "ranger":      "earth tones, multiple layers, weather-adapted — looks like they've been outside",
    "barbarian":   "minimal — what's worn is chosen for freedom of movement and intimidation",
    "paladin":     "armour polished to a standard, divine marks clearly visible — presence intended",
    "bard":        "expressive and colourful — crafted to draw eyes, change frequently",
    "warlock":     "patron's influence bleeds into their clothes — subtle wrongness in the cut or material",
    "druid":       "natural materials, sometimes still growing — the Undercity version uses Rift-flora",
    "monk":        "stripped down, nothing unnecessary — what's there is perfect quality",
    "sorcerer":    "clothing that reacts to their power — sparks, frost, shadows at the hem",
    "artificer":   "tool harnesses, component belts, goggles, at least one thing that ticks or glows",
    "blood hunter":"scarred, dark, the smell of alchemical reagents — clothing shows the cost of their power",
    "arcane archer":"hunter's practicality with fletcher's precision — everything serves the shot",
}

# Occasion modifiers
OCCASION_NOTES = {
    "combat":       "built for movement and protection — nothing loose, everything secured",
    "diplomacy":    "formal faction colours at their richest, status symbols front and centre",
    "infiltration": "dark, nondescript, faction marks hidden or removed — forgettable by design",
    "downtime":     "relaxed but still character-appropriate — faction colours softened",
    "arena":        "designed to be seen: bright, dramatic, showing scars proudly",
    "church":       "respectful to the divine — appropriate to the specific god being addressed",
    "market":       "practical shopping wear — valuables hidden, hands free",
    "tavern":       "comfortable, lived-in — enough to show status without being a target",
    "warrens":      "practical and low-profile — nothing worth stealing visible",
    "guild meeting":"rank displayed, faction colours present — professional but armed",
}


# ---------------------------------------------------------------------------
# Core agent function
# ---------------------------------------------------------------------------

async def describe_character_style(
    char_name:   str,
    char_class:  str = "",
    faction:     str = "independent",
    occasion:    str = "general",
    extra_notes: str = "",
) -> str:
    """
    Generate a vivid, Undercity-grounded clothing and style description
    for the given character in the given context.

    Returns a Discord-formatted string.
    """
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    # Build context from faction/class/occasion data
    faction_key  = faction.lower().replace(" ", "_").replace("'", "").replace("-", "_")
    faction_data = FACTION_STYLE_NOTES.get(faction_key, FACTION_STYLE_NOTES["independent"])
    class_note   = CLASS_STYLE_NOTES.get(char_class.lower(), "no specific class note")
    occasion_note = OCCASION_NOTES.get(occasion.lower(), "general wear — character's own taste")

    prompt = f"""You are a costume and style designer for the Undercity — a sealed fantasy city that has absorbed
fashion, materials, and aesthetic from hundreds of devoured worlds. Think: dark medieval fantasy base
crossed with salvaged tech, divine silk, alchemical materials, neon enchantment, and post-apocalyptic
patching. Lighting is mostly torch and bioluminescent vials.

CHARACTER: {char_name}
CLASS: {char_class or 'unspecified'}
FACTION: {faction_data['name']}
OCCASION: {occasion} — {occasion_note}
{f'ADDITIONAL NOTES: {extra_notes}' if extra_notes else ''}

FACTION AESTHETIC:
- Palette: {faction_data['palette']}
- Materials: {faction_data['materials']}
- Accessories: {faction_data['accessories']}
- Vibe: {faction_data['vibe']}
- Signature: {faction_data['signature']}

CLASS STYLE TENDENCY: {class_note}

Write a vivid, specific clothing description for this character for this occasion.
Include: primary outfit, colours, key materials, 2-3 specific accessories, footwear, and one distinctive detail
that makes this outfit immediately recognisable as THEIRS.

RULES:
- Be specific and tactile. Name fabrics, describe wear and repair, mention functional details.
- Ground it in the Undercity — no generic "fantasy peasant" or "standard adventurer" descriptions.
- 4-6 lines. Discord markdown: **bold** key items, *italics* for atmosphere.
- Output ONLY the description. No preamble, no sign-off."""

    import httpx
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()

        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()

        lines = text.splitlines()
        skip  = ("sure", "here's", "here is", "certainly", "of course", "below is", "great")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        return "\n".join(lines).strip() or "*Could not generate style description.*"

    except Exception as e:
        import traceback
        logger.error(f"style_agent error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return f"*Style lookup failed: {type(e).__name__}*"


# ---------------------------------------------------------------------------
# Internal enrichment: adds clothing details to /draw prompts
# ---------------------------------------------------------------------------

async def enrich_appearance_prompt(
    base_description: str,
    char_class:       str = "",
    faction:          str = "independent",
) -> str:
    """
    Takes an existing appearance description (e.g. from /setcharappearance)
    and injects faction/class-appropriate clothing detail suitable for SD prompts.

    Returns the enriched description string.
    """
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    faction_key  = faction.lower().replace(" ", "_").replace("'", "").replace("-", "_")
    faction_data = FACTION_STYLE_NOTES.get(faction_key, FACTION_STYLE_NOTES["independent"])
    class_note   = CLASS_STYLE_NOTES.get(char_class.lower(), "")

    prompt = f"""You are enriching a character description for an AI image generator.

EXISTING APPEARANCE DESCRIPTION:
{base_description}

FACTION CLOTHING STYLE ({faction_data['name']}):
- Palette: {faction_data['palette']}
- Materials: {faction_data['materials']}
- Key accessories: {faction_data['accessories']}

CLASS STYLE NOTE ({char_class or 'unspecified'}): {class_note}

Rewrite the description to include specific, vivid clothing details that fit both the character
and their faction. Keep physical features from the original. Add outfit, colours, materials,
and 1-2 accessories. Max 3 sentences. Written as Stable Diffusion prompt tags/phrases.

Output ONLY the enriched description. No preamble."""

    import httpx
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()

        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()

        lines = text.splitlines()
        skip  = ("sure", "here's", "here is", "certainly", "of course", "below is")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        return "\n".join(lines).strip() or base_description

    except Exception as e:
        logger.warning(f"enrich_appearance_prompt error: {e}")
        return base_description  # fallback: return original unchanged


# ---------------------------------------------------------------------------
# Quick reference: what does a faction member typically wear?
# ---------------------------------------------------------------------------

def faction_style_summary(faction: str) -> str:
    """Returns a quick Discord-formatted style summary for a faction."""
    faction_key  = faction.lower().replace(" ", "_").replace("'", "").replace("-", "_")
    data = FACTION_STYLE_NOTES.get(faction_key)
    if not data:
        return f"*No style data for faction: {faction}*"

    return (
        f"**{data['name']} — Style Profile**\n"
        f"🎨 *Palette:* {data['palette']}\n"
        f"🧵 *Materials:* {data['materials']}\n"
        f"💎 *Accessories:* {data['accessories']}\n"
        f"✨ *Vibe:* {data['vibe']}\n"
        f"🔖 *Signature:* {data['signature']}"
    )
