"""
ad_feed.py — In-world advertisement system for the Undercity Discord bot.

Serves rotating ads from local shops and establishments. Ads feel authentic
to the Undercity setting: gritty, specific, noir, with practical D&D utility.

Posts every 3 hours, tracked via global_state DB key 'ad_last_post'.
Dynamic ads optionally generated via Ollama (20% chance per posting).
"""

from __future__ import annotations

import random
import re
import logging
from datetime import datetime, timedelta
from typing import List, Optional

import discord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Static ad pool — 30+ entries
# ---------------------------------------------------------------------------

AD_POOL: List[dict] = [
    # Potion shops
    {
        "shop_name": "Elune's Apothecary",
        "district": "Cobbleway Market",
        "ad_text": (
            "**Potions of Healing** — bulk rates for adventuring parties. "
            "Elune's has supplied the Guild for six years without a single bad batch. "
            "Ask about our *Greater Healing* stock and the healer's kit bundles — "
            "because the Warrens don't care how brave you are."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["healing", "potions", "healer's kit"],
    },
    {
        "shop_name": "The Amber Flask",
        "district": "Hearthstone District",
        "ad_text": (
            "Running dry before the next mission? **The Amber Flask** stocks Standard, Greater, "
            "and Superior Healing Potions — no Guild markup, no questions. "
            "Find us behind the Copper Market, third stall past the lantern post."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["healing", "potions"],
    },
    {
        "shop_name": "Blight & Brew",
        "district": "Neon Row",
        "ad_text": (
            "**Antitoxins. Potions of Resistance. Elixirs of Health.** "
            "If the Undercity is trying to kill you specifically, Blight & Brew has "
            "the counteragent. Open all night, because poison doesn't keep business hours."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["antitoxin", "potions", "resistance"],
    },
    # Weapon smiths
    {
        "shop_name": "Ferric & Sons Armaments",
        "district": "Artisan Quarter",
        "ad_text": (
            "Three generations of blades that don't break when it matters. "
            "**Ferric & Sons** crafts shortswords, longswords, and hand crossbows "
            "to Guild spec — ask about our +1 enchantment upgrade service "
            "and the custom grip programme for off-hand fighters."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["weapons", "+1 weapons", "shortsword", "longsword"],
    },
    {
        "shop_name": "The Iron Covenant",
        "district": "Ironworks",
        "ad_text": (
            "**Weapons forged in Ironworks furnaces.** No filigree. No ceremony. "
            "War hammers, battleaxes, and greataxes that outlast their owners. "
            "Consortium workers get 10% off — everyone else pays full price and is grateful for it."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["weapons", "war hammer", "battleaxe"],
    },
    {
        "shop_name": "Razorthorn Blades",
        "district": "Night Pits",
        "ad_text": (
            "When the arena lights go up, you want **Razorthorn steel** in your hand. "
            "Combat daggers, rapiers, and paired short blades — all balanced for the pit. "
            "Silver coating available for those with *creature* problems."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["weapons", "dagger", "rapier", "silvered weapons"],
    },
    # Armor makers
    {
        "shop_name": "Vault & Rivet",
        "district": "Coppergate",
        "ad_text": (
            "**Studded leather to half-plate** — fitted same-day if we have your measurements on file. "
            "Vault & Rivet has outfitted more D-rank adventurers than any other shop in Ring 4. "
            "We don't assume you'll survive. We make sure your armour does."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["armor", "leather armor", "half-plate"],
    },
    {
        "shop_name": "The Warden's Forge",
        "district": "Outer Wall",
        "ad_text": (
            "Warden-surplus **chain mail and splint armour** — inspected, repaired, re-fitted. "
            "Built for the Wall, available to the city. "
            "Shield repairs while you wait. Bring proof of Warden service for retired pricing."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["armor", "chain mail", "shield"],
    },
    {
        "shop_name": "Duskweave Tailors",
        "district": "Duskhollow",
        "ad_text": (
            "**Arcane-threaded robes and spell-resistant leathers** for those who work in the dark. "
            "Duskweave garments come with mage-stitched pockets, silence-treated soles, "
            "and a lining that won't betray you under *detect magic*."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["armor", "mage armor", "stealth", "arcane focus"],
    },
    # Scroll scribes
    {
        "shop_name": "The Cataloguing Hand",
        "district": "Archive Row",
        "ad_text": (
            "**Scrolls of Identify** — 75 EC per scroll, bulk rates for archivist patrons. "
            "We also stock *detect magic*, *comprehend languages*, and *remove curse*. "
            "Every scroll verified by a Glass Sigil licensed scribe. No fakes. "
            "No excuses."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["scrolls", "identify scroll", "magic", "detect magic"],
    },
    {
        "shop_name": "Inkwright's Scriptorium",
        "district": "Artisan Quarter",
        "ad_text": (
            "Custom scroll scribing — **any spell up to 5th level** with a 3-day lead time. "
            "Bring your own spell slot or pay the premium casting fee. "
            "Combat utility scrolls in stock: *haste*, *hold person*, *counterspell*. "
            "The Guild trusts us. You should too."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["scrolls", "magic", "haste", "counterspell"],
    },
    # Enchantment shops
    {
        "shop_name": "The Resonant Mark",
        "district": "Academy Heights",
        "ad_text": (
            "**Weapon and armour enchantments** by licensed Wizards Tower artificers. "
            "+1 to +3 upgrades, elemental damage infusions, and protective ward bonuses. "
            "All enchantments come with a certificate of authenticity and a 30-day guarantee against "
            "Rift interference degradation."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["enchantment", "+1 weapons", "+2 weapons", "magic items"],
    },
    {
        "shop_name": "Sigil & Seal",
        "district": "Guild Spires",
        "ad_text": (
            "**Arcane focuses, spell component pouches, and wondrous items** — "
            "certified for Guild use. Sigil & Seal keeps a rotating stock of "
            "*rings of protection*, *cloaks of elvenkind*, and *boots of striding*. "
            "Come in before your next mission. Walk out harder to kill."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["magic items", "arcane focus", "ring of protection", "cloak of elvenkind"],
    },
    # Taverns with adventurer specials
    {
        "shop_name": "The Laughing Skull",
        "district": "Neon Row",
        "ad_text": (
            "**The Skull's Adventurer Board**: post-mission meals, mission-prep tab extensions, "
            "and a private room for party planning — no Warden ears, guaranteed. "
            "Complimentary *healer's kit* with every party booking of six or more."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["tavern", "adventurers", "healer's kit"],
    },
    {
        "shop_name": "The Last Round",
        "district": "Night Pits",
        "ad_text": (
            "Fighter's fuel. **The Last Round** serves hot food, healing draughts by the mug, "
            "and a no-questions policy for anyone walking in post-arena. "
            "We've seen worse than whatever you're carrying. Sit down."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["tavern", "healing", "fighters"],
    },
    {
        "shop_name": "The Smoking Wand",
        "district": "Academy Heights",
        "ad_text": (
            "**Faculty rates on all drinks.** Students present your Academy token for 20% off. "
            "Quiet corners for spell review, study group rooms by reservation, "
            "and a standing order of *spell component pouches* behind the bar — "
            "because you always forget yours on exam day."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["tavern", "spell components", "arcane focus"],
    },
    # Spell component suppliers
    {
        "shop_name": "Reagent Row Collective",
        "district": "Academy Heights",
        "ad_text": (
            "**Full spell component inventory** — bat guano, diamond dust, powdered iron, "
            "rare inks, and anything else the Tower syllabi demand. "
            "Reagent Row suppliers operate under Glass Sigil quality standards. "
            "If it's not in stock, we'll source it within 48 hours."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["spell components", "magic", "rare components"],
    },
    {
        "shop_name": "The Root & Residue",
        "district": "Sanctum Quarter",
        "ad_text": (
            "**Holy water, sacred incense, diamond dust for *revivify* — and the real thing, "
            "not the Cobbleway knockoffs.** The Root & Residue has supplied Serpent Choir "
            "contract scribes for twelve years. Divine spellcasters trust us because "
            "the gods notice the difference."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["spell components", "holy water", "healing", "revivify"],
    },
    # Tool vendors
    {
        "shop_name": "Grapple & Grind",
        "district": "Scrapworks",
        "ad_text": (
            "**Thieves' tools, climbing gear, grappling hooks, and 50-foot coils** — "
            "salvage-quality materials at fraction-of-new prices. "
            "Everything tested before it leaves the yard. Grapple & Grind: "
            "because the Warrens don't care about your Guild-issue kit."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["thieves' tools", "climbing gear", "tools"],
    },
    {
        "shop_name": "The Careful Hand",
        "district": "Coppergate",
        "ad_text": (
            "**Lockpicks, trap-finding kits, disguise supplies, and forgery components** — "
            "sold as 'novelty items' and covered under Coppergate merchant ordinance 7-C. "
            "Wink optional. Discretion guaranteed."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["thieves' tools", "disguise kit", "forgery kit"],
    },
    # Mount/familiar handlers
    {
        "shop_name": "The Tether & Claw",
        "district": "Floating Bazaar",
        "ad_text": (
            "**Familiars, bonded mounts, and arcane companions** for the discerning adventurer. "
            "Current stock: ravens, owls, weasels, and a bonded **pseudodragon** — "
            "paperwork provided. We also board existing familiars while you're in the Warrens."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["familiar", "find familiar", "pseudodragon", "mount"],
    },
    # Healing temples
    {
        "shop_name": "The Pilgrim's Rest Infirmary",
        "district": "Sanctum Quarter",
        "ad_text": (
            "**Short-rest healing services** — lay on hands surrogates, lesser restoration, "
            "and *cure wounds* at tiered Guild rates. The Pilgrim's Rest Infirmary does not ask "
            "what mission you came from. We ask what hurts and we fix it."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["healing", "cure wounds", "lesser restoration", "lay on hands"],
    },
    {
        "shop_name": "Cathedral of the Eternal Flame — Alms Office",
        "district": "Temple Row",
        "ad_text": (
            "**Free lesser restoration for the genuinely destitute.** The Eternal Flame does not "
            "turn away the afflicted. For those with coin, *greater restoration* services are "
            "available by appointment. Bring your contract record — the Choir does not work blind."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["healing", "lesser restoration", "greater restoration"],
    },
    # Arcane academies
    {
        "shop_name": "The Wizards Tower — Evening Courses",
        "district": "Academy Heights",
        "ad_text": (
            "**Evening enrolment now open.** Introduction to Cantrips, Intermediate Transmutation, "
            "and Advanced Rift Theory — taught by Tower-certified Mages. "
            "Scholarships available for ranked adventurers. "
            "*Arcane focus included in course materials.*"
        ),
        "bulletin_type": "news",
        "dnd_tags": ["arcane focus", "magic", "spellcasting"],
    },
    {
        "shop_name": "The Glass Sigil Study Halls",
        "district": "Archive Row",
        "ad_text": (
            "**Research access passes** — three-day, seven-day, and monthly. "
            "The Grand Archive Dome holds the most complete collection of pre-Rift texts "
            "in the Undercity. If you need *identify* results, lore verification, "
            "or spell research, this is where you come."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["identify scroll", "lore", "research"],
    },
    # Thieves' supplies
    {
        "shop_name": "Under the Counter",
        "district": "Duskhollow",
        "ad_text": (
            "**Everything the Guild doesn't officially sell.** Poisons, smoke bombs, "
            "caltrops, and *dust of disappearance* — sourced from where you don't need to know. "
            "Night Market hours only. No Warden tokens. No credit."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["thieves' tools", "poison", "stealth"],
    },
    {
        "shop_name": "Shadowthread Outfitters",
        "district": "Collapsed Plaza",
        "ad_text": (
            "**Cloaks of the Manta Ray, dark vision goggles, and custom black-dyed leathers** "
            "for those who work where the lights don't reach. Prices are negotiable. "
            "Location is not advertised. You know how to find us or you don't."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["stealth", "darkvision", "cloak"],
    },
    # General adventurer gear
    {
        "shop_name": "Relic Row Outfitters",
        "district": "Markets Infinite",
        "ad_text": (
            "**Full adventuring kit — explorer's pack, dungeoneer's pack, or burglar's pack** — "
            "assembled and ready to go. Relic Row also carries recovered magic items "
            "on consignment: no provenance, no warranty, genuine price. "
            "Everything's been *identify*'d by a licensed scribe."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["adventuring gear", "explorer's pack", "magic items"],
    },
    {
        "shop_name": "The Dead Weight Supply Co.",
        "district": "Shantytown Heights",
        "ad_text": (
            "**Rope, pitons, torches, iron rations, and ten-foot poles** — "
            "the things that save your life that the fancy shops don't stock. "
            "Dead Weight delivers to the Warrens access points. "
            "We've been keeping the bottom of the city alive for eight years."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["adventuring gear", "torches", "rations"],
    },
    {
        "shop_name": "The Gilded Quill Trading Post",
        "district": "Grand Forum",
        "ad_text": (
            "**Rare maps, dungeon survey reports, and point-of-interest briefings** — "
            "information is the most valuable commodity in the Undercity. "
            "The Gilded Quill brokers verified Rift zone maps and Warren charts. "
            "D-rank and above only. Bring your Guild token."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["maps", "navigation", "scouting"],
    },
    # Specialty shops
    {
        "shop_name": "Ashen Relics & Curios",
        "district": "The Reliquary",
        "ad_text": (
            "**Sanctioned artifact appraisal and limited sale.** "
            "Under Glass Sigil charter, Ashen Relics sells studied items cleared for public ownership — "
            "*rings of mind shielding*, *necklaces of adaptation*, and miscellaneous wondrous items. "
            "Rift-touched objects priced separately."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["magic items", "ring of mind shielding", "wondrous items"],
    },
    {
        "shop_name": "Patchwork Pharmacy",
        "district": "Ember Ward",
        "ad_text": (
            "**Saints-run, community-priced.** Healer's kits, bandages, *herbalism kit* supplies, "
            "and unlabelled potions of healing — sliding scale pricing, no one turned away. "
            "Leave what you can. Take what you need."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["healing", "herbalism kit", "healer's kit", "potions"],
    },
    {
        "shop_name": "The Neutral Ground Armourers",
        "district": "Diplomats Row",
        "ad_text": (
            "**Ceremonial arms and formal armour** for faction functions, diplomatic events, "
            "and occasions where you need to look dangerous without being obvious about it. "
            "Our *+1 longswords* come with a scabbard that has never seen a battlefield. "
            "That's the point."
        ),
        "bulletin_type": "news",
        "dnd_tags": ["armor", "weapons", "+1 longsword"],
    },
]


# ---------------------------------------------------------------------------
# Recent ad tracker — avoid repeats within last 10 posts
# ---------------------------------------------------------------------------

_recent_ad_indices: List[int] = []
_RECENT_WINDOW = 10


async def get_next_ad() -> dict:
    """Return a random ad, mixing static AD_POOL with nightly-generated ads (40% generated when available)."""
    # Pull nightly-generated ads from DB
    generated: list = []
    try:
        from src.db_api import get_global_state
        import json
        raw = get_global_state("generated_ads") or []
        if isinstance(raw, str):
            raw = json.loads(raw)
        generated = [a for a in raw if isinstance(a, dict) and a.get("shop_name") and a.get("ad_text")]
    except Exception:
        pass

    # 40% chance to pick a generated ad when the pool is non-empty
    if generated and random.random() < 0.40:
        return random.choice(generated)

    # Otherwise pick from static pool, avoiding recent repeats
    available = [i for i in range(len(AD_POOL)) if i not in _recent_ad_indices]
    if not available:
        _recent_ad_indices.clear()
        available = list(range(len(AD_POOL)))

    idx = random.choice(available)
    _recent_ad_indices.append(idx)
    if len(_recent_ad_indices) > _RECENT_WINDOW:
        _recent_ad_indices.pop(0)

    return AD_POOL[idx]


# ---------------------------------------------------------------------------
# Dynamic ad generation via Ollama
# ---------------------------------------------------------------------------

async def generate_dynamic_ad(shop_name: str, district: str, dnd_tags: list) -> str:
    """
    Generate a fresh punchy ad via Ollama (qwen3-8b-slim).
    Returns the generated ad text, or falls back to the static version on failure.
    """
    try:
        from src.ollama_queue import call_ollama, OllamaBusyError
        import os

        ollama_model = os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest")
        tags_str = ", ".join(dnd_tags) if dnd_tags else "general adventuring"

        prompt = (
            f"You are writing in-world advertisements for shops in the Undercity — "
            f"a dark, gritty, noir underground city sealed under a Dome. "
            f"The tone is specific, punchy, and never generic fantasy. "
            f"Mention real D&D items where relevant.\n\n"
            f"Write a SHORT advertisement (2-3 sentences, Discord markdown OK) for:\n"
            f"Shop: {shop_name}\n"
            f"District: {district}\n"
            f"Relevant D&D items/tags: {tags_str}\n\n"
            f"Output ONLY the ad copy. No preamble, no shop name header, no sign-off."
        )

        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": 200, "think": True, "num_ctx": 8192},
            },
            timeout=60.0,
            caller="ad_feed",
        )

        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()

        # Strip <think> blocks
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

        # Remove leading filler phrases
        lines = text.splitlines()
        skip = ("sure", "here's", "here is", "as requested", "certainly",
                "of course", "i hope", "below is", "absolutely")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)

        result = "\n".join(lines).strip()
        if result:
            return result

    except Exception as e:
        logger.debug(f"📢 Dynamic ad generation failed ({type(e).__name__}: {e}) — using static")

    # Fallback: return empty string — caller will use static ad_text
    return ""


# ---------------------------------------------------------------------------
# Tick check — post every 3 hours
# ---------------------------------------------------------------------------

def check_ad_tick() -> bool:
    """
    Return True if an ad should post this tick.
    Ads post every 3 hours. Tracks last post via global_state key 'ad_last_post'.
    """
    now = datetime.utcnow()
    try:
        from src.db_api import get_global_state, set_global_state
        last_str = get_global_state("ad_last_post")
        if last_str:
            try:
                last_dt = datetime.fromisoformat(str(last_str))
                if now - last_dt < timedelta(hours=3):
                    return False
            except Exception:
                pass
        set_global_state("ad_last_post", now.isoformat())
        return True
    except Exception as e:
        logger.warning(f"📢 Ad tick: DB error ({e}) — posting anyway")
        return True


# ---------------------------------------------------------------------------
# Discord embed formatter
# ---------------------------------------------------------------------------

def _make_ad_preview(text: str, max_chars: int = 200) -> str:
    """Extract first 1-2 sentences — full text lives behind Read More."""
    import re as _re
    if len(text) <= max_chars:
        return text
    sentences = _re.split(r"(?<=[.!?])\s+", text)
    preview = ""
    for s in sentences:
        candidate = (preview + " " + s).strip()
        if len(candidate) <= max_chars:
            preview = candidate
        else:
            break
    if not preview:
        preview = text[:max_chars].rsplit(" ", 1)[0] + "…"
    elif len(preview) < len(text):
        preview += " …"
    return preview


def format_ad_embed(ad: dict) -> discord.Embed:
    """
    Create a styled Discord Embed for an advertisement.
    Gold color (0xFFAA00), short preview in description — full text via Read More button.
    """
    preview = _make_ad_preview(ad.get("ad_text", ""))
    embed = discord.Embed(
        description=preview,
        color=0xFFAA00,
    )
    embed.set_author(name=f"📢 {ad.get('shop_name', 'Unknown Shop')}")
    embed.set_footer(text=f"{ad.get('district', 'The Undercity')} • Read More for full details")
    return embed
