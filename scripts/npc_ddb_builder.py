"""
npc_ddb_builder.py — Build DDB-ready stat blocks for all campaign NPCs.

Data priority (authoritative):
  1. npcs.data_json.stats — current AC/HP/ability scores, class/level/subclass/saves
  2. npcs.data_json.equipment (list) — actual magic items
  3. npcs.data_json.stat_block — custom pre-built stat block (use directly if present)
  4. npc_appearances.appearance_json — sd_appearance prompt for portrait generation

Rules:
  - HP × 1.5 (NPCs get boosted HP in DDB; deal less damage but are tougher)
  - CR derived from level
  - Magic items translated into trait/action abilities
  - Custom stat_block used as-is when present

Run from project root:
    python scripts/npc_ddb_builder.py
"""
from __future__ import annotations

import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv; load_dotenv(ROOT / ".env")
from src.db_api import raw_query

STAGING_FILE = ROOT / "scripts" / "npc_ddb_staging.json"
HP_MULTIPLIER = 1.5

# ── CR by level ───────────────────────────────────────────────────────────────
LEVEL_TO_CR = {
    1: "1/4", 2: "1/2", 3: "1/2", 4: "1",
    5: "2",   6: "2",   7: "3",   8: "3",
    9: "4",   10: "5",  11: "5",  12: "6",
    13: "7",  14: "7",  15: "8",  16: "9",
    17: "10", 18: "11", 19: "12", 20: "13",
}

# ── Species → (creature_type, size) ──────────────────────────────────────────
def species_to_type_size(species: str) -> tuple[str, str]:
    s = (species or "").lower()
    if any(x in s for x in ("specter", "spectre", "ghost", "zombie", "skeleton", "revenant", "undead", "vampire", "wight", "wraith")):
        return ("undead", "M")
    if "warforged" in s or "automaton" in s or "golem" in s:
        return ("construct", "M")
    if any(x in s for x in ("dwarf", "halfling", "gnome", "goblin", "kobold", "deep gnome")):
        return ("humanoid", "S")
    if "formerly" in s:
        inner = s.split("formerly")[-1].strip().rstrip(")")
        return species_to_type_size(inner)
    return ("humanoid", "M")

def _mod(score: int) -> int:
    return (score - 10) // 2

def _sign(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)

# ── Magic item → trait text ───────────────────────────────────────────────────
# Items that provide meaningful combat abilities (not just passive +1s)
ITEM_TRAITS: dict[str, str] = {
    "Cloak of Invisibility":
        "Cloak of Invisibility. The NPC can become invisible as an action. "
        "Lasts up to 2 hours total (can be divided into 1-minute segments). "
        "Ends if the NPC attacks or casts a spell.",
    "Staff of Power":
        "Staff of Power (+2 spell attack/DC, 20 charges). The NPC gains +2 to spell attack rolls and spell save DC. "
        "Can expend charges to cast: Cone of Cold (5), Fireball (5th level, 5), Globe of Invulnerability (6), "
        "Hold Monster (5), Levitate (2), Lightning Bolt (5th level, 5), Magic Missile (1), Ray of Enfeeblement (1), Wall of Force (5).",
    "Robe of the Archmagi":
        "Robe of the Archmagi. +2 to spell attack rolls and spell save DC. "
        "Advantage on saving throws against spells and magical effects. "
        "The NPC's AC is 15 + Dexterity modifier while wearing it.",
    "Vorpal Longsword":
        "Vorpal Longsword (+3). +3 to attack and damage rolls. "
        "Critical hits (20, or 18-20 with improved crit) sever the target's head (instant death unless immune), "
        "or deal an extra 6d8 slashing damage to targets without a head.",
    "Defender Longsword":
        "Defender Longsword (+3). Before attacking, the NPC can transfer up to +3 bonus from the weapon "
        "to AC instead. Transfer resets each turn.",
    "Scarab of Protection":
        "Scarab of Protection. The NPC has advantage on saving throws against spells. "
        "If a spell would slay the NPC outright (Power Word Kill, disintegrate), they can use their reaction "
        "to destroy the scarab and have the spell fail instead (12 charges).",
    "Robe of Eyes":
        "Robe of Eyes. The NPC sees in all directions and has darkvision 120 ft. "
        "Advantage on Perception checks. Cannot be surprised. Can see invisible creatures.",
    "Helm of Telepathy":
        "Helm of Telepathy. The NPC can use Detect Thoughts at will (DC 13 Wisdom save). "
        "While concentrating on it, can send telepathic messages to any creature within 30 ft. "
        "that it is reading. Can use reaction to plant a suggestion (DC 13 Wis or follow for 1 hour).",
    "Helm of Brilliance":
        "Helm of Brilliance. The NPC sheds bright light 30 ft. when wearing the helm fully charged. "
        "Can cast Fire Ball (fire, 7d6) as an action consuming one ruby. "
        "Fire-based attacks deal +1d6 fire damage. Any undead within 30 ft. take 1d6 radiant/turn.",
    "Ioun Stone, Fortitude":
        "Ioun Stone, Fortitude. Maximum HP increased by 25.",
    "Boots of Levitation":
        "Boots of Levitation. Can cast Levitate on self at will (10-minute duration).",
    "Figurine of Wondrous Power, Obsidian Steed":
        "Obsidian Steed (Figurine). Once per week (24 hours), can summon a Nightmare as a mount. "
        "The Nightmare can become ethereal as a bonus action while mounted.",
    "Bag of Tricks, Tan":
        "Bag of Tricks (Tan). As an action, throw a fuzzy object (3/day). "
        "One of: Brown Bear, Giant Badger, Badger, Boar, Panther appears and follows commands.",
    "Bag of Tricks, Gray":
        "Bag of Tricks (Gray). Summons: Weasel, Giant Rat, Badger, Boar, Panther, Giant Badger, or Brown Bear.",
    "Bag of Tricks, Rust":
        "Bag of Tricks (Rust). Summons: Rat, Owl, Mastiff, Goat, Giant Goat, Giant Boar, or Lion.",
    "Cloak of the Bat":
        "Cloak of the Bat. In dim light or darkness, can polymorph into a bat as a bonus action "
        "(no equipment transforms). Also has advantage on Stealth checks in dim light/darkness.",
    "Horn of Valhalla, Iron":
        "Horn of Valhalla (Iron). Once every 7 days, summons 2d4+2 berserker warriors who fight for 1 hour. "
        "Requires proficiency in heavy armor to use; otherwise they attack the NPC.",
    "Pearl of Power":
        "Pearl of Power. Once per day, can regain one expended spell slot of 3rd level or lower.",
    "Dread Helm":
        "Dread Helm. Eyes glow red, face invisible in shadow. Advantage on Intimidation checks. "
        "Enemies who can see the NPC's face at start of turn (within 30 ft.) must DC 13 Wisdom save or be frightened until end of their next turn.",
    "Gloves of Thievery":
        "Gloves of Thievery. +5 to Sleight of Hand checks and Dexterity checks to pick locks "
        "or disable devices (invisible while worn).",
    "Boots of Elvenkind":
        "Boots of Elvenkind. Advantage on Dexterity (Stealth) checks that rely on sound.",
    "Prehistoric Figurine of Wondrous Power, Carnelian Triceratops":
        "Carnelian Triceratops (Figurine). Can summon a Triceratops once per week (24 hrs). "
        "Triceratops acts on the NPC's initiative and follows simple commands.",
    "Manual of Bodily Health":
        "Manual of Bodily Health (Used). Constitution score and maximum are permanently increased by 2.",
    "Hat of Vermin":
        "Hat of Vermin. 3/day as an action, speak a command and a CR 0 vermin (bat, frog, rat) "
        "appears in the hat. Mostly minor utility/distraction.",
    "Rope of Mending":
        "Rope of Mending. The NPC can use a bonus action to mend a cut piece of rope within touch (minor).",
    "+3 Amulet of the Devout":
        "+3 Amulet of the Devout. +3 to spell attack rolls and spell save DC for clerics/paladins.",
    "+3 Wand of the War Mage":
        "+3 Wand of the War Mage. +3 to spell attack rolls. Ignore half and three-quarters cover.",
    "+2 Wand of the War Mage":
        "+2 Wand of the War Mage. +2 to spell attack rolls. Ignore half cover.",
    "+2 Rod of the Pact Keeper":
        "+2 Rod of the Pact Keeper. +2 to spell attack rolls and spell save DC for warlocks. "
        "Can regain one warlock spell slot as an action (1/long rest).",
    "+3 Rod of the Pact Keeper":
        "+3 Rod of the Pact Keeper. +3 to spell attack rolls and DC. Regain one slot 1/long rest.",
    "Enduring Spellbook":
        "Enduring Spellbook. Spellbook is immune to fire and water damage.",
    "Boots of the Winterlands":
        "Boots of the Winterlands. Ignore difficult terrain from ice/snow. Resist cold damage. "
        "Can tolerate -50°F temperatures without protection.",
}

# Items that only add flat bonuses (already reflected in AC/saves stats) — skip as traits
PASSIVE_BONUS_ITEMS = {
    "Ring of Protection", "Cloak of Protection", "Ioun Stone, Protection",
    "Pearl of Power", "+1 Leather Armor", "+2 Leather Armor", "+3 Leather Armor",
    "+1 Plate Armor", "+2 Plate Armor", "+3 Plate Armor",
    "+1 Chain Mail", "+2 Chain Mail", "+3 Chain Mail",
    "+1 Chain Shirt", "+2 Chain Shirt", "+1 Scale Mail", "+2 Scale Mail",
    "Chain Mail", "Chain Shirt", "Scale Mail", "Plate Armor", "Leather Armor",
    "+1 Shield", "+2 Shield", "+3 Shield", "Shield",
    "+1 Longsword", "+2 Longsword",
    "+1 Rapier", "+2 Rapier",
    "+1 Mace", "+1 Shortsword", "+1 Longbow",
    "+1 Quarterstaff", "+1 Scale Mail",
    "Arcane Focus", "Holy Symbol", "Lute", "Dagger",
    "Bag of Holding", "Rope of Climbing",
    "Scholar's Pack", "Explorer's Pack", "Burglar's Pack",
    "Entertainer's Pack", "Priest's Pack",
    "Heward's Handy Spice Pouch", "Cloak of Billowing", "Cloak of Many Fashions",
    "Hat of Wizardry", "Ear Horn of Hearing", "Horn of Silent Alarm",
    "Ancient Tome", "Scroll of Identify", "Enduring Spellbook",
    "Quaal's Feather Token, Tree",
    "Scholar's Robes", "Dark Robes",
    "Smith's Tools", "Quiver of Arrows", "Thieves' Tools",
    "Rope of Mending",
}


def items_to_traits(items: list) -> list[str]:
    """Convert equipment list into meaningful trait strings for DDB."""
    traits = []
    for it in items:
        if not isinstance(it, dict):
            continue
        nm = it.get("name", "")
        if nm in PASSIVE_BONUS_ITEMS:
            continue
        if nm in ITEM_TRAITS:
            traits.append(ITEM_TRAITS[nm])
        elif nm and not any(x in nm for x in ("Pack", "Potion", "Tools", "Robes", "Scroll", "Quill", "Ink", "Paper")):
            # Generic entry for unrecognised named items
            traits.append(f"{nm}. (Equipped magic item — see DMG for full rules.)")
    return traits


# ── Class action templates ────────────────────────────────────────────────────
def _wpn_from_items(items: list, cls: str) -> tuple[str, str, str]:
    """Return (weapon_name, die, dmg_type) from equipped items."""
    for it in items:
        nm = (it.get("name","") if isinstance(it, dict) else "").lower()
        if "vorpal longsword" in nm or "defender longsword" in nm:
            return ("Longsword", "1d8", "slashing")
        if "rapier" in nm:
            return ("Rapier", "1d8", "piercing")
        if "longsword" in nm:
            return ("Longsword", "1d8", "slashing")
        if "greatsword" in nm:
            return ("Greatsword", "2d6", "slashing")
        if "greataxe" in nm:
            return ("Greataxe", "1d12", "slashing")
        if "mace" in nm or "warhammer" in nm:
            return ("Warhammer", "1d8", "bludgeoning")
        if "quarterstaff" in nm or "staff of power" in nm:
            return ("Quarterstaff", "1d6", "bludgeoning")
        if "shortsword" in nm or "dagger" in nm and "rogue" in cls.lower():
            return ("Shortsword", "1d6", "piercing")
        if "battleaxe" in nm or "axe" in nm:
            return ("Battleaxe", "1d8", "slashing")
        if "longbow" in nm or "crossbow" in nm:
            return ("Longbow", "1d8", "piercing")
    # Default by class
    cls_l = cls.lower()
    if cls_l in ("wizard", "sorcerer", "warlock"):
        return ("Dagger", "1d4", "piercing")
    if cls_l in ("rogue", "bard"):
        return ("Rapier", "1d8", "piercing")
    if cls_l in ("cleric", "druid"):
        return ("Mace", "1d6", "bludgeoning")
    if cls_l in ("barbarian",):
        return ("Greataxe", "1d12", "slashing")
    return ("Longsword", "1d8", "slashing")


def _magic_bonus(items: list, wpn_name: str) -> int:
    """Return the enhancement bonus for the primary weapon."""
    for it in items:
        nm = (it.get("name","") if isinstance(it, dict) else "").lower()
        wpn_l = wpn_name.lower()
        if wpn_l in nm:
            for bonus in (3, 2, 1):
                if f"+{bonus}" in nm:
                    return bonus
    return 0


def build_actions(stats: dict, cls: str, level: int, pb: int,
                  subclass: str, items: list) -> str:
    cl = cls.lower()
    str_s = stats.get("STR", 10)
    dex_s = stats.get("DEX", 10)
    con_s = stats.get("CON", 10)
    int_s = stats.get("INT", 10)
    wis_s = stats.get("WIS", 10)
    cha_s = stats.get("CHA", 10)

    wpn_name, wpn_die, dmg_type = _wpn_from_items(items, cls)
    magic_bonus = _magic_bonus(items, wpn_name)

    # Attack stat
    if cl in ("wizard", "sorcerer"):
        atk_stat_mod = _mod(int_s if cl == "wizard" else cha_s)
        uses_str = False
    elif cl in ("rogue", "monk", "ranger", "bard"):
        atk_stat_mod = _mod(dex_s)
        uses_str = False
    elif cl == "warlock":
        atk_stat_mod = _mod(cha_s)
        uses_str = False
    elif cl in ("cleric", "paladin"):
        atk_stat_mod = _mod(str_s)
        uses_str = True
    else:
        atk_stat_mod = _mod(str_s)
        uses_str = True

    atk_total = atk_stat_mod + pb + magic_bonus
    die_sides = int(wpn_die.split("d")[-1])
    avg_dmg = int(die_sides / 2 + 0.5 + atk_stat_mod + magic_bonus)
    dmg_str = f"{wpn_die}+{atk_stat_mod + magic_bonus}" if (atk_stat_mod + magic_bonus) >= 0 else f"{wpn_die}{atk_stat_mod + magic_bonus}"

    lines = []

    # Multiattack
    atk_count = 3 if level >= 11 and cl in ("fighter", "paladin", "ranger", "barbarian", "blood hunter") else \
                2 if level >= 5 and cl in ("fighter", "paladin", "ranger", "barbarian", "blood hunter", "monk") else 1
    if atk_count > 1:
        lines.append(f"Multiattack. Makes {atk_count} {wpn_name} attacks.")

    # Main weapon attack
    wpn_bonus_note = f" (+{magic_bonus} magic)" if magic_bonus else ""
    lines.append(
        f"{wpn_name}{wpn_bonus_note}. Melee Weapon Attack: {_sign(atk_total)} to hit, reach 5 ft., one target. "
        f"Hit: {avg_dmg} ({dmg_str}) {dmg_type} damage."
    )

    # Class-specific additions
    if cl == "rogue":
        sneak_d = max(1, (level + 1) // 2)
        lines.append(
            f"Sneak Attack (1/Turn). When the rogue has advantage or an ally is within 5 ft. of the target, "
            f"deals an extra {sneak_d}d6 piercing damage on a hit."
        )

    elif cl in ("wizard", "sorcerer"):
        spell_mod = _mod(int_s if cl == "wizard" else cha_s)
        spell_atk = spell_mod + pb
        spell_dc  = 8 + spell_mod + pb
        # Check for wand bonus
        for it in items:
            nm = (it.get("name","") if isinstance(it, dict) else "").lower()
            if "wand of the war mage" in nm or "rod of the pact keeper" in nm:
                for bonus in (3, 2, 1):
                    if f"+{bonus}" in nm:
                        spell_atk += bonus; spell_dc += bonus; break
                break
        # Robe bonus
        for it in items:
            nm = (it.get("name","") if isinstance(it, dict) else "").lower()
            if "robe of the archmagi" in nm or "amulet of the devout" in nm:
                spell_atk += 2; spell_dc += 2; break
        cantrip_d = 1 + (level // 6)
        lines.append(
            f"Fire Bolt. Ranged Spell Attack: {_sign(spell_atk)} to hit, 120 ft. "
            f"Hit: {cantrip_d * 5} ({cantrip_d}d10) fire damage."
        )
        lines.append(
            f"Spellcasting (DC {spell_dc}, {_sign(spell_atk)} to hit). Spells include: "
            + ("Magic Missile (1st), Thunderwave (1st), Shield (reaction). " if level >= 1 else "")
            + ("Misty Step (2nd), Mirror Image (2nd). " if level >= 3 else "")
            + ("Fireball (3rd), Counterspell (3rd). " if level >= 5 else "")
            + ("Polymorph (4th), Greater Invisibility (4th). " if level >= 7 else "")
            + ("Cone of Cold (5th), Telekinesis (5th). " if level >= 9 else "")
            + ("Disintegrate (6th), Chain Lightning (6th). " if level >= 11 else "")
            + ("Finger of Death (7th). " if level >= 13 else "")
        )

    elif cl == "warlock":
        spell_mod = _mod(cha_s)
        spell_atk = spell_mod + pb
        spell_dc  = 8 + spell_mod + pb
        for it in items:
            nm = (it.get("name","") if isinstance(it, dict) else "").lower()
            if "rod of the pact keeper" in nm:
                for bonus in (3, 2, 1):
                    if f"+{bonus}" in nm:
                        spell_atk += bonus; spell_dc += bonus; break
                break
        eb_beams = 1 + (level >= 5) + (level >= 11) + (level >= 17)
        lines.append(
            f"Eldritch Blast ({eb_beams} beam{'s' if eb_beams>1 else ''}). "
            f"Ranged Spell Attack: {_sign(spell_atk)} to hit, 120 ft. "
            f"Hit: 6 (1d10+{_mod(cha_s)}) force damage per beam."
            + (" (Agonizing Blast adds CHA modifier to each beam.)" if level >= 2 else "")
        )
        lines.append(
            f"Spellcasting (DC {spell_dc}). Pact Slots: {pb} × level {min(5,1+(level-1)//4)}. "
            "Known: Hex, Misty Step"
            + (", Hunger of Hadar (3rd)" if level >= 5 else "")
            + (", Banishment (4th)" if level >= 7 else "")
            + (", Hold Monster (5th)" if level >= 9 else "")
            + "."
        )

    elif cl == "cleric":
        spell_mod = _mod(wis_s)
        spell_dc  = 8 + spell_mod + pb
        spell_atk = spell_mod + pb
        for it in items:
            nm = (it.get("name","") if isinstance(it, dict) else "").lower()
            if "amulet of the devout" in nm:
                for bonus in (3, 2, 1):
                    if f"+{bonus}" in nm:
                        spell_atk += bonus; spell_dc += bonus; break
                break
        lines.append(
            f"Sacred Flame. DC {spell_dc} Dexterity save or {pb}d8 radiant (no cover benefit)."
        )
        lines.append(
            f"Spellcasting (DC {spell_dc}, {_sign(spell_atk)} to hit). Spells: "
            "Cure Wounds, Guiding Bolt, Bless, Spiritual Weapon"
            + (", Dispel Magic, Revivify" if level >= 5 else "")
            + (", Banishment, Guardian of Faith" if level >= 7 else "")
            + (", Flame Strike, Raise Dead" if level >= 9 else "")
            + (", Harm, Heal" if level >= 11 else "")
            + "."
        )

    elif cl == "paladin":
        spell_mod = _mod(cha_s)
        spell_dc  = 8 + spell_mod + pb
        smite_die = min(5, 1 + (level // 3))
        lines.append(
            f"Divine Smite. On hit with a melee weapon: expend a spell slot to deal "
            f"extra radiant damage (2d8 per slot level)."
        )
        lines.append(
            f"Spellcasting (DC {spell_dc}). Paladin spells: Bless, Shield of Faith, Divine Favor"
            + (", Aid, Find Steed" if level >= 5 else "")
            + (", Blinding Smite, Revivify" if level >= 9 else "")
            + "."
        )

    elif cl == "ranger":
        lines.append(
            "Hunter's Mark (Bonus Action). Marks one creature: +1d6 damage on hits against it. "
            "Concentration, 1 hour."
        )
        lines.append(
            "Colossus Slayer (1/Turn). +1d8 damage against targets below their HP maximum."
        )

    elif cl == "barbarian":
        lines.append(
            f"Reckless Attack. Attacks with advantage. Until next turn, attacks against it also have advantage."
        )

    elif cl == "bard":
        spell_mod = _mod(cha_s)
        spell_dc  = 8 + spell_mod + pb
        lines.append(
            f"Vicious Mockery. DC {spell_dc} Wisdom save or {pb}d4 psychic damage + disadvantage on next attack."
        )
        lines.append(
            f"Spellcasting (DC {spell_dc}). Bard spells: Healing Word, Dissonant Whispers, Hypnotic Pattern"
            + (", Polymorph, Greater Invisibility" if level >= 7 else "")
            + "."
        )

    elif cl == "monk":
        martial_die = "1d8" if level >= 5 else "1d6"
        stun_dc = 8 + pb + _mod(wis_s)
        lines.append(f"Flurry of Blows (1 Ki). Two bonus-action Unarmed Strikes.")
        lines.append(
            f"Stunning Strike (1 Ki, on hit). DC {stun_dc} Constitution save or Stunned until end of next turn."
        )

    elif cl == "druid":
        spell_mod = _mod(wis_s)
        spell_dc  = 8 + spell_mod + pb
        spell_atk = spell_mod + pb
        lines.append(
            f"Shillelagh. Melee Spell Attack: {_sign(spell_atk)} to hit. Hit: {5+_mod(wis_s)} (1d8+{_mod(wis_s)}) bludgeoning (magical)."
        )
        lines.append(
            f"Spellcasting (DC {spell_dc}). Druid spells: Entangle, Thunderwave, Moonbeam"
            + (", Call Lightning, Conjure Animals" if level >= 5 else "")
            + (", Wind Walk, Heal" if level >= 11 else "")
            + "."
        )

    elif cl == "blood hunter":
        lines.append(
            "Crimson Rite (Bonus Action). Imbues weapon with fire, lightning, or necrotic: +1d6 extra damage per hit "
            "but takes 1d4 damage at start of each turn. Ends on short/long rest."
        )
        curse_dc = 8 + pb + _mod(wis_s)
        lines.append(
            f"Blood Curse of Binding (1/Day). One creature within 30 ft.: DC {curse_dc} Strength save "
            "or Restrained until end of next turn. On fail by 5+: also takes 2d6 necrotic."
        )

    elif cl == "artificer":
        spell_atk = _mod(int_s) + pb
        spell_dc  = 8 + _mod(int_s) + pb
        lines.append(
            f"Arcane Firearm. Ranged Spell Attack: {_sign(spell_atk)} to hit, 120 ft. "
            f"Hit: {2*5} (2d10) lightning or fire damage (infused weapon choice)."
        )
        lines.append(
            f"Infused Weapon. The artificer's primary weapon deals an extra 1d6 damage per hit."
        )
        lines.append(
            f"Spellcasting (DC {spell_dc}, {_sign(spell_atk)} to hit). Prepared spells: "
            "Cure Wounds, Faerie Fire, Shield of Faith"
            + (", Shatter, Web" if level >= 3 else "")
            + (", Fly, Haste" if level >= 5 else "")
            + (", Arcane Eye, Fabricate" if level >= 9 else "")
            + "."
        )

    return "\n\n".join(lines)


def build_traits(stats: dict, cls: str, level: int, pb: int,
                 subclass: str, species: str, faction: str,
                 items: list, has_custom_sb: bool) -> str:
    cl = cls.lower()
    str_s = stats.get("STR", 10)
    dex_s = stats.get("DEX", 10)
    con_s = stats.get("CON", 10)
    int_s = stats.get("INT", 10)
    wis_s = stats.get("WIS", 10)
    cha_s = stats.get("CHA", 10)

    lines = []

    # Species traits
    sp = (species or "").lower()
    if any(x in sp for x in ("specter", "spectre", "ghost", "undead", "zombie", "skeleton", "vampire")):
        lines.append(
            "Undead Nature. Immune to poison damage, the poisoned condition. "
            "Doesn't require air, food, drink, or sleep."
        )
        if "specter" in sp or "spectre" in sp or "ghost" in sp:
            lines.append(
                "Incorporeal Movement. Can move through creatures and objects as difficult terrain. "
                "Takes 5 (1d10) force damage if ending turn inside an object."
            )
    if "vampire" in sp:
        lines.append(
            "Undead Fortitude. If damage would reduce to 0 HP, make DC 15 Con save. "
            "On success, drop to 1 HP instead. Doesn't work vs. radiant or critical hits."
        )
    if "dwarf" in sp or "mountain dwarf" in sp or "hill dwarf" in sp:
        lines.append("Dwarven Resilience. Advantage on saves vs. poison. Resistance to poison damage.")

    # Class features
    if cl == "fighter":
        lines.append(
            f"Action Surge (1/Short Rest). Takes one additional action on its turn."
        )
        if level >= 9:
            lines.append("Indomitable (1/Long Rest). Rerolls one failed saving throw.")
        if subclass and "champion" in subclass.lower():
            lines.append("Improved Critical. Scores a critical hit on a 19 or 20.")
        if subclass and "battle master" in subclass.lower():
            lines.append(
                f"Battle Master (4 superiority dice, d{8 if level < 10 else 10 if level < 18 else 12}). "
                "Maneuvers include: Precision Attack (+die to attack), Riposte (reaction attack on miss), "
                "Commander's Strike (bonus action ally attack), Goading Attack (target makes Wis save or "
                "has disadvantage attacking others)."
            )

    elif cl == "rogue":
        lines.append("Cunning Action. Takes the Dash, Disengage, or Hide action as a bonus action.")
        if level >= 5:
            lines.append("Uncanny Dodge. As a reaction, halves damage from one attack it can see.")
        if level >= 7:
            lines.append("Evasion. Takes no damage on successful Dex save for half; half on fail.")
        if subclass and "assassin" in subclass.lower():
            lines.append(
                "Assassinate. Advantage on attacks vs. creatures that haven't taken a turn. "
                "Hits against surprised creatures are automatic critical hits."
            )
        if subclass and "mastermind" in subclass.lower():
            lines.append(
                "Master of Tactics. Can use Help as a bonus action from up to 30 ft. "
                "Can mimic any accent or speech patterns after 1 minute of listening."
            )
        if level >= 11:
            lines.append("Reliable Talent. Treat any skill proficiency roll below 10 as a 10.")

    elif cl == "warlock":
        slot_level = min(5, 1 + (level - 1) // 4)
        lines.append(
            f"Pact Magic. Has {pb} spell slots of level {slot_level} that recharge on a short rest."
        )
        lines.append(
            f"Dark One's Blessing. On reducing a hostile to 0 HP, gains {cha_s + pb} temporary HP."
        )
        if level >= 5:
            lines.append(
                "Eldritch Invocations include: Agonizing Blast (CHA to EB), Repelling Blast (push 10 ft.), "
                "Devil's Sight (120-ft. darkvision through magical darkness)."
            )

    elif cl == "cleric":
        lines.append(
            f"Channel Divinity (1/Short Rest). Can use Turn Undead (DC {8+pb+_mod(wis_s)} Wisdom or turned). "
            "Can destroy undead of CR 1/2 or lower at 5th level."
        )
        if level >= 8:
            lines.append(
                f"Potent Spellcasting. Adds Wisdom modifier ({_sign(_mod(wis_s))}) to cleric cantrip damage."
            )

    elif cl in ("wizard", "sorcerer"):
        if cl == "wizard":
            lines.append(
                f"Arcane Recovery (1/Long Rest). Regains spell slots totaling level {level // 2} or lower on short rest."
            )
        if subclass and "loremaster" in subclass.lower():
            lines.append(
                "Loremaster. Knows one additional language per Int modifier. "
                "Can recall specific information about a creature's weaknesses (DC 15 Int check)."
            )
        if subclass and "wild magic" in subclass.lower():
            lines.append(
                "Wild Magic Surge. When casting a spell, DM may trigger a surge. "
                "Tides of Chaos: gain advantage once per long rest; DM can then force a surge."
            )
        if level >= 10:
            lines.append("Spell Mastery. Can cast one 1st and one 2nd-level spell at will without slots.")

    elif cl == "paladin":
        lines.append(
            f"Aura of Protection (10 ft.). Friendly creatures within 10 ft. add CHA modifier "
            f"({_sign(_mod(cha_s))}) to all saving throws."
        )
        lines.append(
            f"Lay on Hands ({level * 5} HP pool). Restore HP to a touched creature as an action."
        )
        if level >= 7:
            lines.append("Aura of Courage (10 ft.). Friendly creatures within 10 ft. can't be frightened.")

    elif cl == "ranger":
        lines.append(
            f"Favored Enemy. Advantage on Survival/Investigation checks to track favored enemy type."
        )
        if level >= 6:
            lines.append("Extra Attack. Makes an additional attack on the Attack action.")

    elif cl == "barbarian":
        rage_dmg = 2 + (2 if level >= 9 else 0) + (1 if level >= 16 else 0)
        lines.append(
            f"Rage ({2+level//6}/Long Rest). While raging: +{rage_dmg} melee damage, advantage on STR checks/saves, "
            "resistance to bludgeoning/piercing/slashing. Lasts 1 minute."
        )
        if level >= 7:
            lines.append("Feral Instinct. Advantage on Initiative. Can't be surprised while not incapacitated.")

    elif cl == "monk":
        ki_pts = level
        unarmed_die = "1d6" if level < 5 else ("1d8" if level < 11 else ("1d10" if level < 17 else "1d12"))
        lines.append(
            f"Ki Points ({ki_pts}/Short Rest). Spends on: Flurry of Blows (2 bonus unarmed strikes), "
            "Patient Defense (Dodge as bonus), Step of the Wind (Dash/Disengage as bonus). "
            f"Unarmed Strike deals {unarmed_die}+{_mod(dex_s)}."
        )
        if level >= 4:
            lines.append("Slow Fall (Reaction). Reduce fall damage by 5 × level.")
        if level >= 10:
            lines.append(
                "Purity of Body. Immune to disease and poison. Doesn't age."
            )

    elif cl == "bard":
        insp_die = "1d6" if level < 5 else ("1d8" if level < 10 else ("1d10" if level < 15 else "1d12"))
        lines.append(
            f"Bardic Inspiration ({max(1,_mod(cha_s))}/Long Rest). Grants one creature a {insp_die} "
            "Bardic Inspiration die (10 min to use on attack, ability check, or saving throw)."
        )
        lines.append(
            "Jack of All Trades. Adds half proficiency bonus to any non-proficient ability check."
        )
        if level >= 6:
            lines.append(
                "Countercharm (Action). While maintaining, allies within 30 ft. have advantage on saves "
                "vs. being frightened or charmed."
            )

    elif cl == "druid":
        uses = level // 2
        lines.append(
            f"Wild Shape ({uses}/Short Rest). Transforms into a beast (CR {max(1,level//4)} or lower)."
        )
        if level >= 6:
            lines.append(
                "Wild Shape improvement: Can transform into beasts with swim or fly speeds."
            )

    elif cl == "blood hunter":
        lines.append(
            "Crimson Rite. As a bonus action, imbues weapon with an elemental damage type (+1d6 extra damage). "
            "Takes 1d4 unpreventable damage at the start of each of its turns while rite is active."
        )
        if level >= 6:
            lines.append("Blood Maledict (2/Short Rest). Can apply a Blood Curse (see action options).")

    # Proficiency note
    sub_note = f" ({subclass})" if subclass and subclass.lower() != "none" else ""
    lines.append(
        f"Proficiency Bonus {_sign(pb)}. Level {level} {cls}{sub_note} — {faction}."
    )

    # Item traits — the kharma-purchased gear
    item_traits = items_to_traits(items)
    if item_traits:
        lines.append("=== Magic Items ===")
        lines.extend(item_traits)

    return "\n\n".join(lines)


def build_reactions(stats: dict, cls: str, level: int, pb: int) -> str:
    cl = cls.lower()
    if cl == "rogue" and level >= 5:
        return (
            "Uncanny Dodge. When an attacker the rogue can see hits it, halves the damage taken."
        )
    elif cl == "fighter":
        dex_s = stats.get("DEX", 10)
        return (
            "Protection (if shield equipped). When a creature the fighter can see attacks "
            "a target within 5 ft., imposes disadvantage on the attack roll."
        )
    elif cl in ("wizard", "sorcerer"):
        spell_mod = _mod(stats.get("INT", 10) if cl == "wizard" else stats.get("CHA", 10))
        return (
            f"Shield (1st-level spell). +5 AC until start of next turn when hit by an attack "
            "(potentially negating the triggering hit)."
        )
    elif cl == "paladin":
        return (
            "Divine Shield. When a friendly creature within 10 ft. is hit, imposes disadvantage on the attack."
        )
    elif cl == "bard":
        return (
            "Cutting Words. Expend one Bardic Inspiration die to subtract the result from "
            "a creature's attack roll, ability check, or damage roll (within 60 ft., can see)."
        )
    elif cl == "cleric" and level >= 6:
        return (
            "Divine Intervention. Once per long rest, the cleric can call on their deity. "
            "At level 10+ this always works. Below 10: percentage chance = level."
        )
    elif cl == "monk" and level >= 4:
        return (
            f"Slow Fall. Reduces fall damage by {level * 5} when falling."
        )
    return ""


def build_bonus_actions(stats: dict, cls: str, level: int, pb: int) -> str:
    cl = cls.lower()
    if cl == "rogue":
        return "Cunning Action. Takes the Dash, Disengage, or Hide action."
    elif cl == "fighter":
        return f"Second Wind. Regains 1d10+{level} HP (1/short rest)."
    elif cl == "barbarian":
        return "Rage. Enters rage (see Traits)."
    elif cl == "monk":
        return "Flurry of Blows (1 Ki). Two Unarmed Strikes after the Attack action."
    elif cl == "warlock":
        cha_mod = _mod(stats.get("CHA", 10))
        return f"Hex (Concentration, 1 hour). Curses target: +1d6 necrotic on hits; adv on ability checks against it."
    elif cl == "cleric":
        wis_mod = _mod(stats.get("WIS", 10))
        return f"Spiritual Weapon (2nd-level spell). Floating weapon: {_sign(wis_mod + pb)} to hit, 1d8{_sign(wis_mod)} force."
    elif cl == "ranger":
        return "Hunter's Mark. Marks target: +1d6 damage on hits (concentration, 1 hour)."
    elif cl == "paladin":
        return "Divine Smite (on hit). Expend a spell slot for extra radiant damage (2d8 per slot level)."
    elif cl == "bard":
        level_to_die = 6 if level < 5 else (8 if level < 10 else (10 if level < 15 else 12))
        return f"Bardic Inspiration. Grants one creature a d{level_to_die} inspiration die."
    elif cl == "blood hunter":
        return "Crimson Rite. Imbues weapon with elemental damage (fire/lightning/necrotic) for +1d6 per hit."
    return ""


def jload(v):
    if isinstance(v, str):
        try: return json.loads(v)
        except: return {}
    return v or {}


def main():
    # Load portrait image paths
    ir_rows = raw_query("SELECT entity_name, image_path FROM image_refs WHERE entity_type='npc_portrait'")
    image_refs = {r["entity_name"]: r["image_path"] for r in ir_rows}
    print(f"Loaded {len(image_refs)} existing NPC portrait paths")

    # Load sd_appearance prompts from npc_appearances
    na_rows = raw_query("SELECT npc_name, appearance_json FROM npc_appearances")
    sd_by_name: dict[str, str] = {}
    for r in na_rows:
        aj = jload(r["appearance_json"])
        sd = aj.get("sd_appearance") or ""
        if sd:
            sd_by_name[r["npc_name"]] = sd

    # Load all NPCs
    npc_rows = raw_query(
        "SELECT id, name, faction, role, status, data_json FROM npcs ORDER BY name"
    )
    print(f"Loaded {len(npc_rows)} NPCs")

    results = []
    skipped = []

    for r in npc_rows:
        name    = r["name"]
        dj      = jload(r.get("data_json"))

        # ── All stats come from data_json.stats (authoritative, current)
        stats   = dj.get("stats") or {}
        if not stats or not stats.get("HP"):
            skipped.append(f"{name} (no stats)")
            continue

        level    = int(stats.get("level") or dj.get("level") or 1)
        cls      = str(stats.get("class") or dj.get("dnd_class") or "Fighter")
        subclass = str(stats.get("subclass") or "")
        if subclass.lower() in ("none", "null", ""):
            subclass = ""
        pb       = int(stats.get("proficiency_bonus") or max(2, (level - 1) // 4 + 2))
        saves    = list(stats.get("save_proficiencies") or [])
        species  = str(dj.get("species") or "Human")
        faction  = str(r.get("faction") or dj.get("faction") or "Unknown")

        # Equipment: prefer data_json.equipment (list of dicts), fall back to appearance
        raw_eq = dj.get("equipment")
        if isinstance(raw_eq, list):
            items = raw_eq
        elif isinstance(raw_eq, dict):
            # Old dict format {armour: ..., weapons: ...} — no item list
            items = []
        else:
            items = []

        # Custom stat block (Vexrath etc)
        custom_sb = dj.get("stat_block") or {}

        creature_type, size = species_to_type_size(species)
        cr        = LEVEL_TO_CR.get(min(level, 20), "5")
        hp_die    = str(stats.get("hit_die") or "d8").replace("d","")
        if not hp_die.isdigit():
            hp_die = "8"

        # Current stats
        str_s = stats.get("STR", 10); dex_s = stats.get("DEX", 10)
        con_s = stats.get("CON", 10); int_s = stats.get("INT", 10)
        wis_s = stats.get("WIS", 10); cha_s = stats.get("CHA", 10)
        ac    = stats.get("AC", 12)
        base_hp  = stats.get("HP", 10)
        boosted_hp = math.ceil(base_hp * HP_MULTIPLIER)

        hp_die_count = level
        con_mod      = _mod(con_s)
        hp_modifier  = con_mod * level

        pp = 10 + _mod(wis_s) + pb  # assume perception proficiency

        # Save bonuses dict
        save_bonuses: dict[str, int] = {}
        ability_mod_map = {"STR": _mod(str_s), "DEX": _mod(dex_s), "CON": _mod(con_s),
                           "INT": _mod(int_s), "WIS": _mod(wis_s), "CHA": _mod(cha_s)}
        for s in saves:
            su = s.upper()
            save_bonuses[su.lower()] = ability_mod_map.get(su, 0) + pb

        # Build content
        if custom_sb:
            # Use existing custom stat block
            actions_text   = "\n\n".join(custom_sb.get("actions", []))
            traits_text    = "\n\n".join(custom_sb.get("traits", []))
            reactions_text = "\n\n".join(custom_sb.get("reactions", []))
            bonus_acts     = "\n\n".join(custom_sb.get("bonus_actions", []))
        else:
            actions_text   = build_actions(stats, cls, level, pb, subclass, items)
            traits_text    = build_traits(stats, cls, level, pb, subclass, species, faction, items, bool(custom_sb))
            reactions_text = build_reactions(stats, cls, level, pb)
            bonus_acts     = build_bonus_actions(stats, cls, level, pb)

        portrait_path = image_refs.get(name)
        if portrait_path and not Path(portrait_path).exists():
            portrait_path = None
        sd_appearance = sd_by_name.get(name, "")

        entry = {
            "name":          name,
            "faction":       faction,
            "role":          str(r.get("role") or dj.get("role") or ""),
            "status":        r.get("status", "alive"),
            "level":         level,
            "cls":           cls,
            "subclass":      subclass,
            "species":       species,
            "cr":            cr,
            "creature_type": creature_type,
            "size":          size,
            "ac":            ac,
            "hp":            boosted_hp,
            "hp_base":       base_hp,
            "hp_die":        hp_die,
            "hp_die_count":  hp_die_count,
            "str_":          str_s,
            "dex":           dex_s,
            "con":           con_s,
            "int_":          int_s,
            "wis":           wis_s,
            "cha":           cha_s,
            "passive_perc":  pp,
            "saves":         save_bonuses,
            "pb":            pb,
            "languages":     "Common",
            "actions":       actions_text,
            "traits":        traits_text,
            "reactions":     reactions_text,
            "bonus_actions": bonus_acts,
            "legendary_actions": "",
            "mythic_actions": "",
            "lair_actions":  "",
            "notes":         f"Level {level} {cls}{(' ('+subclass+')') if subclass else ''} — {faction}.",
            "speeds":        [(4, 40)] if any(x in species.lower() for x in ("ghost", "specter", "spectre")) else [(1, 30)],
            "portrait_path": portrait_path,
            "sd_appearance": sd_appearance,
            "has_custom_sb": bool(custom_sb),
            "item_count":    len(items),
            "ddb_slug":      None,
        }

        results.append(entry)

    print(f"\nBuilt {len(results)} NPC stat blocks")
    print(f"Skipped {len(skipped)}: {skipped[:10]}")
    print(f"With existing portraits: {sum(1 for e in results if e['portrait_path'])}")
    print(f"Need art generation:     {sum(1 for e in results if not e['portrait_path'])}")
    print(f"With custom stat_block:  {sum(1 for e in results if e['has_custom_sb'])}")
    print(f"With magic items:        {sum(1 for e in results if e['item_count'] > 0)}")

    from collections import Counter
    print(f"\nStatus: {dict(Counter(e['status'] for e in results))}")
    print(f"Classes: {dict(sorted(Counter(e['cls'] for e in results).items(), key=lambda x:-x[1]))}")

    # Sample: show a gear_tier NPC
    for e in results:
        if e["item_count"] >= 10 and e["level"] >= 15:
            print(f"\n=== SAMPLE: {e['name']} (Lv{e['level']} {e['cls']}, {e['item_count']} items) ===")
            print(f"CR {e['cr']}, HP {e['hp']} (base {e['hp_base']}), AC {e['ac']}")
            print(f"Traits preview:\n{e['traits'][:400]}...")
            print(f"\nActions preview:\n{e['actions'][:300]}...")
            break

    STAGING_FILE.write_text(
        json.dumps(results, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8"
    )
    print(f"\nStaging file: {STAGING_FILE}")
    print(f"Total: {len(results)} import candidates")


if __name__ == "__main__":
    main()
