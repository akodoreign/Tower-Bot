"""
npc_appearance.py — Generate and store rich appearance/style/stat profiles for all NPCs.

For each NPC in the database, generates:
  - Physical appearance (from existing roster field, enhanced)
  - Class + estimated stats appropriate to their role
  - Equipment appropriate to class/faction/role
  - Style description for Stable Diffusion (based on race, class, faction aesthetic)

Stored in: MySQL npc_appearances table
Also rebuilds npc_roster.txt for RAG system.

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
from src.db_api import raw_query, raw_execute, db

# Keep NPC_APP_DIR for backward compatibility with npc_lifecycle.py references
DOCS_DIR         = Path(__file__).resolve().parent.parent / "campaign_docs"
NPC_APP_DIR      = DOCS_DIR / "npc_appearances"
NPC_ROSTER_FILE  = DOCS_DIR / "npc_roster.json"   # imported by cogs/images.py for /gearrun
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

# ─── Race → Stable Diffusion visual description ──────────────────────────────
# Injected into SD prompts so the image model understands exotic species.
# Ordered longest-key-first so substring matching picks the most specific entry.

RACE_SD_TRAITS: dict[str, str] = {
    # ── Core PHB 2024 ────────────────────────────────────────────────────────
    "human":           "human, normal humanoid proportions, no unusual features",
    "half-elf":        "half-elf, slightly pointed ears, graceful humanoid, otherworldly but approachable",
    "high elf":        "high elf, tall slender humanoid, sharply pointed ears, angular elegant face, no body hair, ethereal",
    "wood elf":        "wood elf, pointed ears, tanned copper skin, lean athletic build, green or amber eyes",
    "dark elf":        "dark elf drow, pointed ears, dark grey or obsidian skin, white or silver hair, pale glowing eyes",
    "drow":            "dark elf drow, pointed ears, dark grey or obsidian skin, white or silver hair, pale glowing eyes",
    "eladrin":         "eladrin elf, pointed ears, faintly luminous skin that shifts with seasons, otherworldly glow",
    "sea elf":         "sea elf, pointed ears, blue-green or seafoam skin, webbed fingers, deep blue eyes",
    "shadar-kai":      "shadar-kai, pointed ears, pale ash-grey skin, dark shadows beneath eyes, ghostly quality",
    "elf":             "elf, tall slender humanoid, sharply pointed ears, angular face, ageless quality",
    "hill dwarf":      "dwarf, stocky 4.5ft humanoid, broad shoulders, thick beard, heavy brow",
    "mountain dwarf":  "dwarf, stocky 4.5ft humanoid, broad shoulders, stone-hard muscles, thick braided beard",
    "dwarf":           "dwarf, stocky 4.5ft humanoid, broad shoulders, thick beard or braids, heavy build",
    "lightfoot halfling": "halfling, 3ft tall humanoid, curly hair, large bare feet, round cheerful face, large eyes",
    "stout halfling":  "halfling, 3ft tall humanoid, slightly broader build, curly hair, large feet, ruddy cheeks",
    "halfling":        "halfling, 3ft tall humanoid, curly hair, large bare feet, round face, large bright eyes",
    "forest gnome":    "gnome, small humanoid under 3ft, large bright eyes, long nose, wild hair, quick movements",
    "rock gnome":      "gnome, small humanoid under 3ft, large eyes, prominent nose, goggles or spectacles often",
    "deep gnome":      "deep gnome svirfneblin, small pale grey-skinned humanoid, bald or sparse white hair, large dark eyes",
    "gnome":           "gnome, small humanoid under 3ft, large expressive eyes, prominent nose",
    "half-orc":        "half-orc, 6ft+ humanoid, greenish grey skin, prominent lower tusks, heavy muscled frame",
    "orc":             "orc, massive humanoid, deep green or slate grey skin, heavy prominent tusks, thick neck and jaw",
    "tiefling":        "tiefling, humanoid with small curved horns, long thin tail, solid-colored eyes, skin in red or purple or lavender tones, slightly sharp teeth",
    "aasimar":         "aasimar, humanoid with faintly glowing skin, silver or gold undertones, luminous eyes, occasional wings of light emerging",
    "dragonborn":      "dragonborn, tall scaled humanoid with a clear draconic lizard head, long snout, scales covering entire body, no human nose, no human hair, no human ears, tail, 6ft+",
    "goliath":         "goliath, enormous humanoid 7ft+, mottled grey and white stone-like skin, bony protrusions on brow and skull, bald",
    # ── Extended PHB and sourcebooks ─────────────────────────────────────────
    "firbolg":         "firbolg, giant-kin humanoid 7-8ft, barrel-chested, large bovine nose, faintly blue-grey or pink skin, mild giant features",
    "satyr":           "satyr, humanoid upper body on goat lower body, small curved horns, pointed ears, goat legs with hooves, fur on lower half",
    "centaur":         "centaur, humanoid torso emerging from horse body, four hooved legs, horse tail, powerful physique",
    "minotaur":        "minotaur, humanoid with bull head and horns, covered in short fur, hooves, muscular 7ft frame, bovine snout",
    "leonin":          "leonin, humanoid lion, tawny or dark fur covering body, full mane, feline face with fangs, clawed hands",
    "loxodon":         "loxodon, humanoid elephant, broad grey trunk for nose, large fan ears, thick tough grey hide, tusks, 7ft",
    "tabaxi":          "tabaxi catfolk, adult humanoid with human-like face structure, cat ears on top of head, light short facial fur, subtle whisker marks, feline eyes, small catlike nose, long tail, lithe",
    "aarakocra":       "aarakocra, humanoid eagle-bird, feathered body, beak, wings on arms or separate, taloned feet, 5ft",
    "kenku":           "kenku, humanoid raven, black iridescent feathers, corvid beak, dark intelligent eyes, 5ft, no wings",
    "owlin":           "owlin, humanoid owl, soft feathers, large forward-facing eyes, short hooked beak, silent wings on back",
    "lizardfolk":      "lizardfolk, reptilian humanoid, scales covering body, slit pupils, flat nose, no hair, long tail, 6ft",
    "tortle":          "tortle, humanoid turtle, large domed shell on back, beak-like mouth, scaled arms, clawed hands, 5ft",
    "yuan-ti":         "yuan-ti pureblood, humanoid with subtle serpent features, forked tongue, slit pupils, patches of scales on skin, cold inhuman eyes",
    "grung":           "grung, small frog humanoid 3ft, brightly colored toxic skin, large sticky hands, wide flat face, large eyes",
    "locathah":        "locathah, fish-humanoid, scaled body, finned ridges, gills on neck, webbed hands, no hair, aquatic features",
    "triton":          "triton, humanoid aquatic, blue-green tinted skin, finned ears, gills, webbed hands, flowing silver or blue hair",
    "tabaxi":          "tabaxi catfolk, adult humanoid with human-like face structure, cat ears on top of head, light short facial fur, subtle whisker marks, feline eyes, small catlike nose, long tail, lithe athletic build",
    # ── Genasi variants ──────────────────────────────────────────────────────
    "fire genasi":     "fire genasi, humanoid with deep red or orange skin, hair that flickers and moves like flame, ember-like eyes",
    "water genasi":    "water genasi, humanoid with blue-green skin, hair that flows like underwater, gills, amphibious features",
    "air genasi":      "air genasi, humanoid with pale or sky-blue tinted skin, constantly moving silver or white hair, light and ethereal",
    "earth genasi":    "earth genasi, humanoid with brown or grey rocky skin, heavy solid build, hair of packed earth or stone",
    "genasi":          "genasi, humanoid with elemental features, unusual skin tone and hair reflecting their element",
    # ── Eberron species ──────────────────────────────────────────────────────
    "changeling":      "changeling, pale featureless humanoid, white hair, colorless grey eyes, features subtly shifting and unfinished-looking",
    "shifter":         "shifter, humanoid with bestial features, slightly elongated canines, clawed fingertips, faint fur on forearms",
    "warforged":       "warforged, humanoid construct of metal and dark wood, no organic features, glowing crystal eyes, plated chest, articulated metal limbs",
    "kalashtar":       "kalashtar, tall slender humanoid, serene angular features, faint luminous quality to skin, deep calm eyes",
    # ── Spelljammer / Astral ─────────────────────────────────────────────────
    "astral elf":      "astral elf, tall pointed-ear humanoid, silver or starfield-blue skin, hair like spun starlight, otherworldly calm",
    "giff":            "giff, 6ft+ humanoid hippopotamus, thick grey hairless hide, broad flat mouth, small eyes, military bearing",
    "hadozee":         "hadozee, monkey humanoid, covered in brown or grey fur, gliding membranes between wrists and ankles, dexterous",
    "thri-kreen":      "thri-kreen, insectoid humanoid, chitinous exoskeleton, six limbs (four arms two legs), mandibles, compound eyes, no hair",
    "plasmoid":        "plasmoid, amorphous semi-translucent ooze-being, roughly humanoid shape with pseudopod limbs, internal organs faintly visible",
    "autognome":       "autognome, small mechanical gnome construct, clockwork gears visible, brass and copper plating, glowing gem eyes",
    # ── Ravnica / Theros ─────────────────────────────────────────────────────
    "vedalken":        "vedalken, slim blue-grey humanoid, bald, three fingers per hand, calm analytical expression",
    "simic hybrid":    "simic hybrid, humanoid with aquatic or animal features grafted on, fins or scales or extra limbs or bioluminescence",
    # ── Monstrous ────────────────────────────────────────────────────────────
    "harengon":              "harengon, humanoid rabbit, tall pointed ears, rabbit snout, large rear feet, fur covering body",
    "aether-touched accursed": "harengon, anthropomorphic hare, tall pointed rabbit ears, dark mottled brown and black fur, amber orange eyes, rabbit snout, digitigrade legs",
    "fairy":           "fairy, tiny 1-2ft humanoid, insect or butterfly wings, delicate features, luminous skin",
    "githyanki":       "githyanki, lean humanoid, yellow-green skin, angular gaunt face, pointed ears, military bearing, sword always present",
    "githzerai":       "githzerai, lean humanoid, pale yellow skin, serene angular face, pointed ears, monastic bearing",
    "hobgoblin":       "hobgoblin, disciplined humanoid, reddish-brown skin, flat broad nose, dark orange or yellow eyes, military posture",
    "bugbear":         "bugbear, large hairy humanoid 7ft, brown or grey fur covering body, bear-like flat face, small dark eyes, long arms",
    "goblin":          "goblin, small 3.5ft humanoid, bright green or yellow-green skin, large flat nose, bat-like ears, wide eyes",
    "kobold":          "kobold, very small reptilian humanoid 2.5ft, narrow lizard snout, scaly skin in reds and browns, small horns, large expressive eyes, wiry body, not human",
    "specter":         "specter, translucent ghostly undead humanoid, faintly luminous edges, hollow eyes, semi-corporeal body, death-touched presence",
    "ghost":           "ghost, translucent ethereal undead humanoid, pale spectral glow, wispy edges, haunted eyes, partially see-through form",
    "revenant":        "revenant, deathless undead humanoid, grey cold skin, sunken eyes, visible scars, grim relentless expression, corpse-touched but intact",
    "wight":           "wight, gaunt undead humanoid, ashen skin, glowing hungry eyes, withered features, old grave-cold presence",
    "lich":            "lich, skeletal undead spellcaster, parchment-dry skin over bone, glowing eyes, ancient regal decay, arcane death aura",
    "shade":           "shade, shadow-touched humanoid, dark translucent skin, smoky silhouette, dim glowing eyes, edges dissolving into darkness",
    "skeleton":        "skeleton, animated humanoid bones, empty eye sockets with faint glow, no skin, visible skull and bony hands",
    "zombie":          "zombie, reanimated undead humanoid, grey torn skin, dull eyes, stiff posture, visible mortal wounds",
    "vampire":         "vampire, pale predatory undead humanoid, sharp fangs, elegant cold features, red or dark eyes, aristocratic menace",
    "dhampir":         "dhampir, pale half-vampire humanoid, subtle fangs, intense eyes, elegant predatory stillness, death-touched beauty",
    # ── Fallback ─────────────────────────────────────────────────────────────
    "unknown":         "humanoid of indeterminate heritage, something subtly unusual in their build or features",
}


SPECIES_PORTRAIT_RULES: dict[str, tuple[str, str]] = {
    "harengon": (
        "Mandatory harengon anatomy: anthropomorphic rabbit humanoid, tall pointed rabbit ears, rabbit snout and nose, fur covering body and face, large rear feet.",
        "ordinary human face, no ears, human nose, bald, scales, cat ears, dog snout",
    ),
    "aether-touched accursed": (
        "Mandatory anatomy: anthropomorphic hare, tall pointed rabbit ears, rabbit snout, dark mottled brown fur, amber eyes. Must read as a rabbit-person, not a human.",
        "ordinary human, human face, no rabbit ears, bald human head, smooth skin, missing fur",
    ),
    "dragonborn": (
        "Mandatory dragonborn anatomy: fully draconic lizard head and snout, scaled face and body, no hair, no human nose, no human ears.",
        "human face, human nose, human ears, human hair, smooth human skin, cat ears, furry mammal face",
    ),
    "tabaxi": (
        "Mandatory tabaxi anatomy: adult catfolk with human-like face structure, light short fur over face and body, cat ears, feline eyes, subtle whisker marks, tail; not a full animal muzzle.",
        "ordinary human, missing cat ears, full animal snout, big cat head, fursuit, heavy fur, dog features, reptile scales",
    ),
    "kobold": (
        "Mandatory kobold anatomy: very small adult reptilian humanoid, narrow lizard snout, scales, small horns, large eyes, wiry frame.",
        "human face, child, toddler, tall dragonborn, goblin ears, mammal fur, cat ears",
    ),
    "halfling": (
        "Mandatory halfling anatomy: short adult humanoid around 3 feet tall, adult face, compact proportions, large expressive eyes, grounded stance.",
        "child, toddler, baby face, giant, tall human, dwarf beard dominance",
    ),
    "gnome": (
        "Mandatory gnome anatomy: very short adult humanoid, clever adult face, bright eyes, prominent nose, wiry compact build.",
        "child, toddler, baby face, tall human, halfling feet focus",
    ),
    "dwarf": (
        "Mandatory dwarf anatomy: short stocky adult humanoid, broad shoulders, heavy brow, dense build, clearly not human height.",
        "tall human, slender elf body, child, halfling proportions",
    ),
    "goblin": (
        "Mandatory goblin anatomy: small wiry adult humanoid, green or yellow-green skin, large ears, wide eyes, sharp nose.",
        "human face, child, tabaxi, cat ears, kobold scales",
    ),
    "lizardfolk": (
        "Mandatory lizardfolk anatomy: reptilian humanoid, scaled body, lizard head, slit pupils, flat reptile nose, no hair, long tail.",
        "human face, human hair, mammal fur, cat ears, dragonborn armor-only cosplay",
    ),
    "tortle": (
        "Mandatory tortle anatomy: turtle humanoid, beak-like mouth, scaled limbs, shell visible behind shoulders, no hair.",
        "human face, human hair, cat ears, smooth human skin",
    ),
    "yuan-ti": (
        "Mandatory yuan-ti anatomy: humanoid with serpent traits, slit pupils, subtle scales, forked tongue or serpentine eyes, cold expression.",
        "ordinary human, cat ears, mammal fur, dragon snout",
    ),
    "kenku": (
        "Mandatory kenku anatomy: raven-like humanoid, black feathers, corvid beak, dark intelligent eyes, no human mouth.",
        "human face, human lips, cat ears, mammal fur, owl face",
    ),
    "owlin": (
        "Mandatory owlin anatomy: owl-like humanoid, soft feathers, large forward-facing eyes, short hooked beak, feathered head.",
        "human face, human lips, cat ears, raven beak, mammal fur",
    ),
    "aarakocra": (
        "Mandatory aarakocra anatomy: bird humanoid, feathered body, beak, taloned hands or feet, avian eyes.",
        "human face, human lips, cat ears, mammal fur, reptile scales",
    ),
    "tiefling": (
        "Mandatory tiefling anatomy: humanoid with horns, tail, unusual skin tone, solid or luminous eyes, subtle sharp teeth.",
        "missing horns, missing tail, ordinary human, cat ears, reptile snout",
    ),
    "warforged": (
        "Mandatory warforged anatomy: humanoid construct, metal and wood plating, articulated limbs, glowing eyes, no organic skin.",
        "human skin, human hair, flesh face, cat ears, reptile scales",
    ),
    "specter": (
        "Mandatory specter anatomy: translucent ghostly undead form, hollow luminous eyes, semi-corporeal edges, death-touched silhouette.",
        "ordinary human skin, solid living body, cheerful healthy complexion",
    ),
    "revenant": (
        "Mandatory revenant anatomy: deathless undead humanoid, cold grey skin, scars, sunken eyes, grim corpse-touched presence.",
        "healthy human complexion, child, glowing angelic skin",
    ),
}


def current_visual_species(species: str) -> str:
    """Return the species the image model should portray right now."""
    raw = (species or "").strip()
    if not raw:
        return "unknown"
    current = re.sub(r"\s*\(formerly\s+[^)]*\)", "", raw, flags=re.IGNORECASE).strip()
    current = re.sub(r"\s*\(former\s+[^)]*\)", "", current, flags=re.IGNORECASE).strip()
    current = re.sub(r"\s*\([^)]*\)", "", current).strip()
    return current or raw


def species_visual_guard(species: str) -> str:
    """Short prompt line that prevents former-race parentheticals from winning."""
    current = current_visual_species(species)
    m = re.search(r"\(formerly\s+([^)]+)\)", species or "", re.IGNORECASE)
    if m:
        former = m.group(1).strip()
        return (
            f"Current species is {current}; former species {former} is backstory only. "
            f"Portray the current {current} form, not a {former}."
        )
    return f"Current species is {current}; portray that species accurately."


def species_portrait_constraints(species: str) -> tuple[str, str]:
    """Return positive and negative prompt fragments for portrait generation."""
    s = current_visual_species(species).lower().strip()
    for key in sorted(SPECIES_PORTRAIT_RULES.keys(), key=len, reverse=True):
        if key in s:
            return SPECIES_PORTRAIT_RULES[key]
    if s and s != "human":
        return (
            f"Mandatory species anatomy: portray this NPC as {current_visual_species(species)}, with visible non-human traits appropriate to that species.",
            "ordinary human, wrong species, missing species traits",
        )
    return ("", "")


def get_race_sd_traits(species: str) -> str:
    """Return SD-prompt visual description for a given species string.
    Matches longest key first to prefer 'high elf' over 'elf'."""
    s = current_visual_species(species).lower().strip()
    for key in sorted(RACE_SD_TRAITS.keys(), key=len, reverse=True):
        if key in s:
            return RACE_SD_TRAITS[key]
    return RACE_SD_TRAITS["unknown"]


def infer_gender_tag(text: str) -> str:
    """Infer 'female' or 'male' from gendered pronouns in description text.
    Returns empty string if ambiguous or no pronouns found."""
    t = (text or "").lower()
    fem  = len(re.findall(r'\bshe\b|\bher\b|\bhers\b|\bherself\b', t))
    masc = len(re.findall(r'\bhe\b|\bhim\b|\bhis\b|\bhimself\b', t))
    if fem > masc:
        return "female"
    if masc > fem:
        return "male"
    return ""


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
    s = current_visual_species(species).lower()
    for key in RACE_PHYSIQUE:
        if key in s:
            return key
    return "unknown"


def _class_key(rank: str, role: str = "") -> str:
    """Map NPC rank + role text to the closest CLASS_PROFILES key.

    Rank alone is often just 'Member' — role text carries the real information.
    We search the combined string so role keywords override the generic rank.
    """
    combined = (rank + " " + role).lower()

    # Direct CLASS_PROFILES key substring match (longest keys first to avoid
    # 'blood hunter' matching 'hunter' before it matches itself)
    for key in sorted(CLASS_PROFILES.keys(), key=len, reverse=True):
        if key in combined:
            return key

    # Role-text keyword fallbacks — ordered most-specific first
    kw = combined
    if any(x in kw for x in ("alchemist", "potion", "alchemy")):      return "artificer"
    if any(x in kw for x in ("intelligence", "informant", "info")):   return "information broker"
    if any(x in kw for x in ("acquisition", "relic", "retrieval")):   return "senior acquisitions agent"
    if any(x in kw for x in ("archive", "librarian", "catalogu")):    return "archivist"
    if any(x in kw for x in ("scroll", "scribe", "legal")):             return "contract scribe"
    if any(x in kw for x in ("mediat", "diplomat", "negotiat")):      return "contract mediator"
    if any(x in kw for x in ("memory", "vial", "psychic")):           return "memory architect"
    if any(x in kw for x in ("heal", "medic", "doctor", "clinic",
                              "resurrect", "divine", "priest")):       return "cleric"
    if any(x in kw for x in ("preach", "sermon", "doctrine",
                              "recruit", "cult", "interpret")):        return "warlock"
    if any(x in kw for x in ("ritual", "spell", "arcane", "magic",
                              "enchant", "rune")):                     return "wizard"
    if any(x in kw for x in ("blade", "sword", "arena", "champion",
                              "bout", "fighter", "combatant")):        return "senior blade"
    if any(x in kw for x in ("patrol", "warden", "guard", "defend",
                              "city wall", "checkpoint")):             return "warden"
    if any(x in kw for x in ("captain", "command", "coordinate",
                              "field leader")):                        return "field captain"
    if any(x in kw for x in ("inspector", "investigate", "inquisit")): return "inspector"
    if any(x in kw for x in ("compliance", "fta", "regulation")):     return "compliance officer"
    if any(x in kw for x in ("speaker", "orator", "broadcast")):      return "speaker"
    if any(x in kw for x in ("acolyte", "novice", "initiat")):        return "acolyte"
    if any(x in kw for x in ("courier", "runner", "messenger", "delivery")): return "street runner"
    if any(x in kw for x in ("smuggl", "shadow", "infiltrat",
                              "assassin", "spy", "dagger")):           return "rogue"
    if any(x in kw for x in ("ranger", "tracker", "hunt", "scout")):  return "ranger"
    if any(x in kw for x in ("bard", "musician", "perform", "song",
                              "network", "social")):                   return "bard"
    if any(x in kw for x in ("sergeant", "officer")):                 return "officer"
    if any(x in kw for x in ("mercenary", "freelance", "prospect")):  return "freelance"
    if any(x in kw for x in ("agent", "broker", "operative")):        return "senior acquisitions agent"
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


# ─── D&D 5e stat block generation ───────────────────────────────────────────

_CLASS_TO_DND: dict[str, tuple[str, str | None]] = {
    "fighter":                   ("Fighter",      None),
    "arcane archer":             ("Fighter",      "Arcane Archer"),
    "rogue":                     ("Rogue",        None),
    "wizard":                    ("Wizard",       None),
    "cleric":                    ("Cleric",       None),
    "ranger":                    ("Ranger",       None),
    "paladin":                   ("Paladin",      None),
    "barbarian":                 ("Barbarian",    None),
    "bard":                      ("Bard",         None),
    "warlock":                   ("Warlock",      None),
    "druid":                     ("Druid",        None),
    "monk":                      ("Monk",         None),
    "sorcerer":                  ("Sorcerer",     None),
    "artificer":                 ("Artificer",    None),
    "blood hunter":              ("Blood Hunter", None),
    # Non-class roles mapped to closest D&D equivalent
    "senior acquisitions agent": ("Rogue",        "Mastermind"),
    "inspector":                 ("Rogue",        "Inquisitive"),
    "information broker":        ("Rogue",        "Mastermind"),
    "archivist":                 ("Wizard",       "Loremaster"),
    "memory architect":          ("Wizard",       "Psionic"),
    "contract mediator":         ("Cleric",       "Order Domain"),
    "field captain":             ("Fighter",      "Battle Master"),
    "speaker":                   ("Bard",         "Eloquence"),
    "senior blade":              ("Fighter",      "Champion"),
    "warden":                    ("Fighter",      "Battle Master"),
    "officer":                   ("Fighter",      "Battle Master"),
    "compliance officer":        ("Rogue",        "Inquisitive"),
    "acolyte":                   ("Cleric",       None),
    "contract scribe":           ("Rogue",        "Mastermind"),
    "mercenary":                 ("Fighter",      None),
    "street runner":             ("Rogue",        None),
    "freelance":                 ("Fighter",      None),
}

_CLASS_HIT_DIE: dict[str, int] = {
    "Barbarian":    12,
    "Fighter":      10,
    "Paladin":      10,
    "Ranger":       10,
    "Blood Hunter": 10,
    "Cleric":       8,
    "Druid":        8,
    "Monk":         8,
    "Rogue":        8,
    "Warlock":      8,
    "Bard":         8,
    "Artificer":    8,
    "Wizard":       6,
    "Sorcerer":     6,
}

_CLASS_SAVES: dict[str, list[str]] = {
    "Fighter":      ["STR", "CON"],
    "Barbarian":    ["STR", "CON"],
    "Paladin":      ["WIS", "CHA"],
    "Ranger":       ["STR", "DEX"],
    "Rogue":        ["DEX", "INT"],
    "Cleric":       ["WIS", "CHA"],
    "Druid":        ["INT", "WIS"],
    "Monk":         ["STR", "DEX"],
    "Bard":         ["DEX", "CHA"],
    "Warlock":      ["WIS", "CHA"],
    "Sorcerer":     ["CON", "CHA"],
    "Wizard":       ["INT", "WIS"],
    "Artificer":    ["CON", "INT"],
    "Blood Hunter": ["DEX", "INT"],
}

# rank keywords → (min_level, max_level)
# Also searched against role text (via _rank_to_level's combined param)
_RANK_LEVELS: list[tuple[list[str], tuple[int, int]]] = [
    (["legendary", "mythic", "demigod"],                                                 (15, 18)),
    (["grand", "arch", "supreme", "high", "head", "director", "master", "grandmaster",
      "final authority", "sets strategy", "commands all"],                               (12, 16)),
    (["leader", "commander", "chief", "matriarch", "patriarch", "widow",
      "sets contract", "approves mission", "strategic direction"],                       (10, 13)),
    (["captain", "senior", "sergeant", "veteran", "lieutenant"],                         (7, 10)),
    (["inspector", "agent", "advocate", "specialist", "broker", "officer"],              (5, 8)),
    (["member", "associate", "operative", "blade", "warden", "scribe", "mediator",
      "archivist", "speaker", "runner"],                                                  (4, 6)),
    (["prospect", "acolyte", "apprentice", "initiate", "novice", "recruit"],            (2, 4)),
]

_STAT_NAMES = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]


def _stat_modifier(score: int) -> int:
    return (score - 10) // 2


def _parse_stat_scores(primary: list, secondary: list) -> dict[str, int]:
    """Parse CLASS_PROFILES primary/secondary lists into a full {STAT: int} dict."""
    scores: dict[str, int] = {}
    pat = re.compile(r"([A-Z]{3})\s+(\d+)")
    for entry in list(primary) + list(secondary):
        if isinstance(entry, str):
            m = pat.search(entry)
            if m:
                scores[m.group(1)] = int(m.group(2))
    for s in _STAT_NAMES:
        if s not in scores:
            scores[s] = 10
    return scores


def _rank_to_level(rank_str: str, npc_name: str = "", role_str: str = "") -> int:
    """Map rank+role text to NPC level. Deterministic per name so gearruns are idempotent."""
    combined = (rank_str + " " + role_str).lower()
    for keywords, (lo, hi) in _RANK_LEVELS:
        if any(kw in combined for kw in keywords):
            offset = abs(hash(npc_name)) % (hi - lo + 1) if npc_name else 0
            return lo + offset
    return 5


def _calc_ac(armour_str: str, stats: dict[str, int], dnd_class: str) -> int:
    """Estimate AC from armour description string."""
    a = armour_str.lower()
    dex = _stat_modifier(stats.get("DEX", 10))
    con = _stat_modifier(stats.get("CON", 10))
    wis = _stat_modifier(stats.get("WIS", 10))
    if "plate" in a and "half" not in a:   return 18
    if "half plate" in a:                  return 15 + min(dex, 2)
    if "chain mail" in a:                  return 16
    if "breastplate" in a:                 return 14 + min(dex, 2)
    if "scale mail" in a:                  return 14
    if "chain shirt" in a:                 return 13 + min(dex, 2)
    if "studded leather" in a:             return 12 + min(dex, 2)
    if "hide" in a:                        return 12 + min(con, 2)
    if "leather" in a:                     return 11 + dex
    if "padded" in a:                      return 11 + dex
    if "no armour" in a or "unarmoured" in a:
        if dnd_class == "Monk":            return 10 + dex + wis
        return 13 + dex  # mage armour
    if any(x in a for x in ("robe", "vestment", "uniform", "coat", "clothing", "none")):
        return 11 + min(dex, 2)
    return 12 + min(dex, 2)


def _calc_hp(dnd_class: str, level: int, con_score: int) -> int:
    """Average HP for the given class and level."""
    die    = _CLASS_HIT_DIE.get(dnd_class, 8)
    con    = _stat_modifier(con_score)
    avg    = (die // 2) + 1           # average die result
    return die + (avg * (level - 1)) + (con * level)


def _proficiency_bonus(level: int) -> int:
    return 2 + (level - 1) // 4


def _build_dnd_statblock(class_key: str, class_prof: dict,
                          rank_str: str, npc_name: str = "",
                          role_str: str = "") -> dict:
    """Return a full D&D 5e-compatible stat block dict for an NPC."""
    dnd_class, subclass = _CLASS_TO_DND.get(class_key, ("Fighter", None))

    scores  = _parse_stat_scores(
        class_prof.get("primary",   ["STR 14", "CON 12", "DEX 10"]),
        class_prof.get("secondary", ["WIS 10", "INT 10", "CHA 10"]),
    )
    level   = _rank_to_level(rank_str, npc_name, role_str)
    armour  = class_prof.get("armour", "leather armour")
    hp      = _calc_hp(dnd_class, level, scores["CON"])
    ac      = _calc_ac(armour, scores, dnd_class)
    prof    = _proficiency_bonus(level)
    saves   = _CLASS_SAVES.get(dnd_class, ["STR", "CON"])

    return {
        "class":              dnd_class,
        "subclass":           subclass,
        "level":              level,
        "STR":                scores["STR"],
        "DEX":                scores["DEX"],
        "CON":                scores["CON"],
        "INT":                scores["INT"],
        "WIS":                scores["WIS"],
        "CHA":                scores["CHA"],
        "HP":                 hp,
        "AC":                 ac,
        "proficiency_bonus":  prof,
        "save_proficiencies": saves,
        "hit_die":            f"d{_CLASS_HIT_DIE.get(dnd_class, 8)}",
    }


async def _generate_npc_profile(npc: dict, force: bool = False) -> dict:
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
    class_key   = _class_key(rank, role)
    faction_key = _faction_key(faction)

    race_note    = RACE_PHYSIQUE.get(race_key, RACE_PHYSIQUE["unknown"])
    race_sd      = get_race_sd_traits(species)
    race_guard   = species_visual_guard(species)
    class_prof   = CLASS_PROFILES.get(class_key, CLASS_PROFILES["mercenary"])
    faction_vis  = FACTION_SD_NOTES.get(faction_key, FACTION_SD_NOTES["independent"])

    # Infer gender from pronouns in the appearance text
    gender_tag = infer_gender_tag(appearance + " " + role)

    # Ask Ollama to write the enriched style description
    ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    prompt = f"""You are writing a visual character profile for an Undercity NPC.
The Undercity is a dark sealed fantasy city containing fashion, materials, and people from all devoured worlds.
Write in the style of a Stable Diffusion image prompt: specific, vivid, tactile, no generic fantasy descriptions.

CHARACTER:
Name: {name}
Species: {species}
Gender: {gender_tag or "unknown"}
Species portrayal rule: {race_guard}
Species visual reference: {race_sd}
Build/physique note: {race_note}
Faction: {faction}
Role/Rank: {rank}
Known appearance: {appearance}
Role summary: {role}
Motivation hint: {motivation}

FACTION VISUAL STYLE: {faction_vis}
CLASS/ROLE EQUIPMENT: {class_prof['weapons']}, wearing {class_prof['armour']}
CLASS STYLE NOTE: {class_prof['style_note']}

Write a SINGLE PARAGRAPH (3-4 sentences) describing this NPC as they would appear in a scene.
Use the species visual reference to accurately describe their physical form — do not describe exotic races as human.
Include: build/height, distinctive species features (ears, scales, fur, horns etc.), skin/hair/eye details, outfit (faction-appropriate), equipment visible on their person, one distinctive visual detail.
Output ONLY the paragraph. No names, no preamble, no sign-off. Written as SD prompt phrases."""

    sd_description = ""
    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=90.0,
            caller="npc_appearance",
            force=force,
        )

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

    # Prepend gender tag if inferred and not already present
    if gender_tag and gender_tag not in sd_description.lower():
        sd_description = f"{gender_tag}, {sd_description}"

    home_district = _location_to_district_key(npc.get("location", ""))

    dnd_stats = _build_dnd_statblock(class_key, class_prof, rank, name, role)

    profile = {
        "name":          name,
        "species":       species,
        "faction":       faction,
        "rank":          rank,
        "role":          class_key,
        "home_district": home_district,
        "dnd_stats":     dnd_stats,
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
    """Legacy path function - kept for compatibility with npc_lifecycle.py."""
    return NPC_APP_DIR / f"{_slug(name)}.json"


def _save_npc_appearance(name: str, profile: dict) -> None:
    """Save an NPC appearance profile to database."""
    try:
        appearance_json = json.dumps(profile, ensure_ascii=False, default=str)
        existing = raw_query(
            "SELECT id FROM npc_appearances WHERE npc_name = %s",
            (name,)
        )
        if existing:
            raw_execute(
                "UPDATE npc_appearances SET appearance_json = %s WHERE npc_name = %s",
                (appearance_json, name)
            )
        else:
            db.insert("npc_appearances", {
                "npc_name": name,
                "appearance_json": appearance_json
            })
    except Exception as e:
        logger.error(f"Failed to save NPC appearance for {name}: {e}")


def get_npc_appearance(name: str) -> Optional[dict]:
    """Load a stored NPC appearance profile from database. Returns None if not yet generated."""
    try:
        rows = raw_query(
            "SELECT appearance_json FROM npc_appearances WHERE npc_name = %s",
            (name,)
        )
        if rows and rows[0].get("appearance_json"):
            data = rows[0]["appearance_json"]
            if isinstance(data, str):
                return json.loads(data)
            return data
        return None
    except Exception as e:
        logger.error(f"Failed to load NPC appearance for {name}: {e}")
        return None


def get_npc_sd_prompt(name: str) -> Optional[str]:
    """Get just the SD-ready appearance description for an NPC."""
    profile = get_npc_appearance(name)
    if not profile:
        return None
    return profile.get("sd_appearance")


def get_all_npc_names() -> list[str]:
    """Return all NPC names from the database."""
    try:
        rows = raw_query("SELECT name FROM npcs WHERE status != 'dead' OR status IS NULL")
        return [row.get("name", "") for row in rows if row.get("name")]
    except Exception as e:
        logger.error(f"Failed to get NPC names: {e}")
        return []


async def generate_all_npc_appearances(force: bool = False) -> dict[str, str]:
    """
    Generate and store appearance profiles for all NPCs in the database.
    Skips NPCs that already have a stored profile unless force=True.
    Returns {name: sd_appearance} for all processed NPCs.
    """
    # Load all NPCs from database
    try:
        rows = raw_query("SELECT * FROM npcs WHERE status != 'dead' OR status IS NULL")
    except Exception as e:
        logger.warning(f"Failed to load NPCs from database: {e}")
        return {}
    
    if not rows:
        logger.warning("No NPCs found in database")
        return {}
    
    results = {}

    for row in rows:
        # Parse NPC data from data_json column
        npc_data = row.get("data_json", {})
        if isinstance(npc_data, str):
            npc_data = json.loads(npc_data) if npc_data else {}
        
        npc = {
            **npc_data,
            "name": row.get("name") or npc_data.get("name", "Unknown"),
            "faction": row.get("faction") or npc_data.get("faction", "Independent"),
            "role": row.get("role") or npc_data.get("role", ""),
            "location": row.get("location") or npc_data.get("location", ""),
            "status": row.get("status") or npc_data.get("status", "alive"),
        }
        
        name = npc.get("name", "")
        if not name:
            continue

        # Check if profile exists in DB
        existing_profile = None if force else get_npc_appearance(name)
        
        if existing_profile and not force:
            results[name] = existing_profile.get("sd_appearance", "")
            logger.info(f"✓ Loaded existing profile: {name}")
            continue

        logger.info(f"⚙ Generating appearance for: {name}")
        try:
            profile = await _generate_npc_profile(npc)
            _save_npc_appearance(name, profile)
            results[name] = profile.get("sd_appearance", "")

            # Write dnd_stats back into npcs.data_json so stat block is live
            dnd = profile.get("dnd_stats")
            if dnd:
                try:
                    npc_row = raw_query("SELECT data_json FROM npcs WHERE name = %s", (name,))
                    if npc_row:
                        existing = npc_row[0].get("data_json") or {}
                        if isinstance(existing, str):
                            existing = json.loads(existing) if existing else {}
                        existing["stats"]     = dnd
                        existing["dnd_class"] = dnd.get("class", "")
                        existing["level"]     = dnd.get("level", 1)
                        raw_execute(
                            "UPDATE npcs SET data_json = %s WHERE name = %s",
                            (json.dumps(existing, ensure_ascii=False), name),
                        )
                except Exception as db_err:
                    logger.warning(f"⚙ Could not write dnd_stats to npcs for {name}: {db_err}")

            logger.info(
                f"✓ Saved profile: {name} "
                f"[{dnd.get('class','?')} {dnd.get('level','?')} | "
                f"HP {dnd.get('HP','?')} AC {dnd.get('AC','?')}]"
            )
        except Exception as e:
            logger.error(f"✗ Failed to generate profile for {name}: {e}")
            results[name] = npc.get("appearance", "")

        # Small delay to not hammer Ollama
        await asyncio.sleep(2)

    return results


def get_all_sd_prompts() -> dict[str, str]:
    """Load all NPC SD prompts from database. Returns {name: sd_prompt}."""
    try:
        rows = raw_query("SELECT npc_name, appearance_json FROM npc_appearances")
        result = {}
        for row in rows:
            name = row.get("npc_name", "")
            data = row.get("appearance_json", {})
            if isinstance(data, str):
                data = json.loads(data) if data else {}
            if name and data:
                result[name] = data.get("sd_appearance", "")
        return result
    except Exception as e:
        logger.error(f"Failed to load SD prompts: {e}")
        # Fallback to flat file if DB fails
        flat_path = NPC_APP_DIR / "_all_sd_prompts.json"
        if flat_path.exists():
            try:
                return json.loads(flat_path.read_text(encoding="utf-8"))
            except Exception:
                pass
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
    Checks stored appearance profile first, then falls back to the database.
    Returns empty string if nothing can be determined.
    """
    # 1. Try stored profile (fast path, already computed)
    profile = get_npc_appearance(name)
    if profile and profile.get("home_district"):
        return profile["home_district"]

    # 2. Fall back to npcs table location field
    try:
        rows = raw_query(
            "SELECT data_json, location FROM npcs WHERE name = %s",
            (name,)
        )
        if rows:
            row = rows[0]
            # Check location column first
            loc = row.get("location", "")
            if loc:
                return _location_to_district_key(loc)
            # Then check data_json
            data = row.get("data_json", {})
            if isinstance(data, str):
                data = json.loads(data) if data else {}
            loc = data.get("location", "")
            return _location_to_district_key(loc)
    except Exception as e:
        logger.error(f"Failed to get home district for {name}: {e}")
    return ""


def find_npc_in_text(text: str, exact_only: bool = False) -> list[tuple[str, str, str]]:
    """
    Scan text for NPC names.
    Returns list of (name, sd_prompt, home_district_key) for every NPC found.
    home_district_key matches the keys in news_feed._DISTRICT_AESTHETICS.
    """
    sd_prompts = get_all_sd_prompts()
    found = []
    text_lower = text.lower()
    for name, prompt in sd_prompts.items():
        full_name_hit = re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", text_lower) is not None
        first = name.split()[0].lower()
        first_name_hit = bool(first) and re.search(rf"(?<!\w){re.escape(first)}(?!\w)", text_lower) is not None
        if full_name_hit or (first_name_hit and not exact_only):
            home = get_npc_home_district(name)
            found.append((name, prompt, home))
    return found


# ─── CLI entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import logging
    force = "--force" in sys.argv
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    loop = asyncio.new_event_loop()
    results = loop.run_until_complete(generate_all_npc_appearances(force=force))
    print(f"\n✅ Generated {len(results)} NPC appearance profiles")
    for name, desc in results.items():
        print(f"\n[{name}]\n  {desc[:120]}...")
