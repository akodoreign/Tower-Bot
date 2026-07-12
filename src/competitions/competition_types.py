"""
competition_types.py — All Undercity competition definitions.

Each CompetitionType defines the format, sponsors, skill pillars, and
round structure for one category of competitive event.

Bracket competitions: seeded, elimination, PC advances round by round.
Judged competitions:  scored on multiple criteria, no bracket, winner by total.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class RoundPhase:
    """One phase within a competition round."""
    name:        str          # "Opening", "Main Contest", "Clincher"
    description: str          # DM-facing description of what happens
    skill:       str          # Primary skill ("Athletics", "Performance", etc.)
    dc_base:     int          # Base DC — scaled by round number in the builder
    advantage_if_prev_won: bool = False  # Advantage if the party won the previous phase


@dataclass(frozen=True)
class CompetitionType:
    slug:            str                   # "combat", "performance", "arcane_duel", etc.
    name:            str                   # Display name
    sponsors:        List[str]             # Primary sponsor factions (in priority order)
    format:          str                   # "bracket" or "judged"
    skill_pillars:   List[str]             # Main skills used across rounds
    phases:          List[RoundPhase]      # Ordered phases per round
    rounds_bracket:  int                   # How many rounds in a bracket (ignored if judged)
    contestants_min: int                   # Minimum contestants to run
    contestants_max: int                   # Max bracket size
    npc_factions:    List[str]             # Factions to pull NPC competitors from
    reward_ec_base:  int                   # Base EC reward for Round 1 win
    reward_ec_final: int                   # EC reward for winning the whole bracket
    kharma_per_win:  int                   # Kharma per round won
    flavor_venues:   List[str]             # Possible venue descriptions
    flavor_crowds:   List[str]             # Crowd composition notes for the DM
    expire_hours:    int = 48              # Hours the round mission stays on the board
    description:     str = ""             # Public-facing description for announcements


# ---------------------------------------------------------------------------
# Type definitions
# ---------------------------------------------------------------------------

COMPETITION_TYPES: List[CompetitionType] = [

    CompetitionType(
        slug           = "combat",
        name           = "Arena Combat",
        sponsors       = ["Argent Blades"],
        format         = "bracket",
        skill_pillars  = ["Athletics", "Acrobatics", "weapon attack", "saving throw"],
        phases         = [
            RoundPhase("Opening Exchange",  "Fighters size each other up. First blood or first knockback sets the tone.",         "Athletics",   12),
            RoundPhase("Main Bout",         "The crowd-defining exchange. Both fighters commit.",                                  "weapon attack", 14, advantage_if_prev_won=True),
            RoundPhase("Clincher",          "One fighter has the edge. The other must survive or turn it around in seconds.",      "saving throw",  16, advantage_if_prev_won=True),
        ],
        rounds_bracket  = 3,
        contestants_min = 4,
        contestants_max = 8,
        npc_factions    = ["Argent Blades", "Wardens of Ash", "Independent", "Patchwork Saints", "Iron Fang Consortium", "Serpent Choir"],
        reward_ec_base  = 500,
        reward_ec_final = 5_000,
        kharma_per_win  = 25,
        flavor_venues   = [
            "the main Arena of Ascendance pit, sand still dark from last night's match",
            "the underground Cage circuit beneath the Arena — no crowd limits down here",
            "the Dust Ring at Guild Spires East — open air, loud, no roof",
            "a Night Pits invitation bout — private seating, private money",
        ],
        flavor_crowds   = [
            "Argent Blades ranking officials in the front row, noting everything",
            "off-duty Wardens in the cheap seats — loud, opinionated",
            "Iron Fang bookmakers moving through the crowd before the bout starts",
            "a delegation from the Patchwork Saints watching one of their own",
            "Obsidian Lotus observers — still, quiet, professionally interested",
        ],
        expire_hours    = 48,
        description     = "Sanctioned combat bouts in the Argent Blades' Arena circuit. Ranked advancement, prize purse, and faction backing on the line.",
    ),

    CompetitionType(
        slug           = "performance",
        name           = "Battle of the Bands",
        sponsors       = ["Serpent Choir", "Adventurers Guild"],
        format         = "bracket",
        skill_pillars  = ["Performance", "Persuasion", "Insight"],
        phases         = [
            RoundPhase("Opening Set",    "The first impression. Hook the crowd or lose them in the first thirty seconds.",   "Performance",  13),
            RoundPhase("Feature Piece",  "The signature work. This is what the act is known for — or wants to be.",          "Persuasion",   15, advantage_if_prev_won=True),
            RoundPhase("Crowd Read",     "Adjust to the room. A judge is watching to see if the performer listens.",         "Insight",      14, advantage_if_prev_won=True),
        ],
        rounds_bracket  = 3,
        contestants_min = 4,
        contestants_max = 8,
        npc_factions    = ["Serpent Choir", "Patchwork Saints", "Adventurers Guild", "Independent"],
        reward_ec_base  = 300,
        reward_ec_final = 3_000,
        kharma_per_win  = 20,
        flavor_venues   = [
            "the Hall of Echoes in the Sanctum Quarter — divine acoustics, literal divine acoustics",
            "the open stage at Pilgrim's Rest — rowdy crowd, bad sightlines, perfect atmosphere",
            "the Grand Forum exhibition stage — civic event, mixed crowd, judges include two city officials",
            "the back room at the Adventurer's Inn — unofficial venue, no rules, very loud",
        ],
        flavor_crowds   = [
            "Serpent Choir clergy in formal attendance — they chose the venue",
            "Saints community members who came for one of the competing acts",
            "a Obsidian Lotus representative here for the memory market potential of a memorable performance",
            "off-duty adventurers who came for the drinks and stayed for the noise",
        ],
        expire_hours    = 36,
        description     = "Multi-act performance bracket across two nights. Serpent Choir judging criteria, Adventurers Guild prize pool.",
    ),

    CompetitionType(
        slug           = "arcane_duel",
        name           = "Arcane Duel Circuit",
        sponsors       = ["Glass Sigil", "Wizards Tower"],
        format         = "bracket",
        skill_pillars  = ["Arcana", "spell attack", "Concentration saving throw"],
        phases         = [
            RoundPhase("Attunement Check",   "Both duellists probe each other's magical signature before committing. What school are they favoring?",  "Arcana",                     14),
            RoundPhase("Spell Exchange",     "The core duel. Spell vs counter, shield vs burst. The warded ring absorbs most of it.",                  "spell attack",               16, advantage_if_prev_won=True),
            RoundPhase("Hold the Weave",     "One duellist is on the back foot. Maintain concentration under sustained pressure or concede.",           "Concentration saving throw",  18, advantage_if_prev_won=True),
        ],
        rounds_bracket  = 3,
        contestants_min = 4,
        contestants_max = 8,
        npc_factions    = ["Wizards Tower", "Glass Sigil", "Guild of Ashen Scrolls", "Serpent Choir", "Independent"],
        reward_ec_base  = 400,
        reward_ec_final = 4_000,
        kharma_per_win  = 20,
        flavor_venues   = [
            "a warded ring in the Arcanum District sub-basement — scorched but structurally sound",
            "the Obsidian Archives' sealed chamber — borrowed for the event, reluctantly",
            "the Glass Sigil's calibration floor — instruments running throughout, data being collected",
            "Wizards Tower's upper demonstration floor — Yaulderna Silverstreak watching from the balcony",
        ],
        flavor_crowds   = [
            "Glass Sigil researchers with notebooks open — this is data collection as much as sport",
            "Wizards Tower apprentices in the gallery, judging technique loudly and incorrectly",
            "a Tower Authority observer — FTA has concerns about energy discharge levels",
            "Varys Thornspire cataloguing the spells used in real time",
        ],
        expire_hours    = 48,
        description     = "Sanctioned spell duels in warded conditions. Judged on technique and control as much as outcome. Glass Sigil and Wizards Tower co-sponsoring.",
    ),

    CompetitionType(
        slug           = "lore",
        name           = "Lore Championship",
        sponsors       = ["Guild of Ashen Scrolls"],
        format         = "bracket",
        skill_pillars  = ["History", "Arcana", "Religion"],
        phases         = [
            RoundPhase("First Category",  "Drawn at random. Any of the three pillars. No preparation advantage.",     "History",   14),
            RoundPhase("Challenger's Pick","The opposing contestant names the category. Pressure is part of the test.", "Arcana",    15, advantage_if_prev_won=True),
            RoundPhase("Archive Question","Eir Velan reads from an unpublished source. No one knows this one.",        "Religion",  17, advantage_if_prev_won=True),
        ],
        rounds_bracket  = 3,
        contestants_min = 4,
        contestants_max = 8,
        npc_factions    = ["Guild of Ashen Scrolls", "Wizards Tower", "Glass Sigil", "Serpent Choir", "Independent"],
        reward_ec_base  = 200,
        reward_ec_final = 2_000,
        kharma_per_win  = 30,
        flavor_venues   = [
            "the Archive's public reading chamber — formal, hushed, smells of old paper",
            "the Fate Gallery on the third floor — portraits of past champions on the walls",
            "the Grand Forum annex — civic event, packed gallery, uncomfortable chairs",
        ],
        flavor_crowds   = [
            "Guild of Ashen Scrolls archivists judging in silence",
            "Tessaly Orin in the audience, allegedly not competing, clearly annoyed she isn't",
            "a scattered audience of academics, adventurers, and one very lost merchant",
        ],
        expire_hours    = 48,
        description     = "Elimination bracket testing History, Arcana, and Religion. Eir Velan administers. The final round question has never been answered correctly twice.",
    ),

    CompetitionType(
        slug           = "craft",
        name           = "Undercity Craft Fair",
        sponsors       = ["Patchwork Saints", "Iron Fang Consortium"],
        format         = "judged",
        skill_pillars  = ["tool proficiency", "Investigation", "Persuasion"],
        phases         = [
            RoundPhase("Craft Submission",  "Create or present the work under time conditions.",              "tool proficiency", 13),
            RoundPhase("Judge Inspection",  "Explain the process and choices to a skeptical judge panel.",    "Persuasion",       14, advantage_if_prev_won=True),
            RoundPhase("Stress Test",       "The judges test the work. Does it hold up?",                     "Investigation",    15, advantage_if_prev_won=True),
        ],
        rounds_bracket  = 1,
        contestants_min = 3,
        contestants_max = 12,
        npc_factions    = ["Patchwork Saints", "Iron Fang Consortium", "Adventurers Guild", "Independent"],
        reward_ec_base  = 250,
        reward_ec_final = 1_500,
        kharma_per_win  = 15,
        flavor_venues   = [
            "the open market floor at Collapsed Plaza — stalls set up overnight",
            "the Saints' community hall in the Warrens — locals providing the judge panel",
            "the Iron Fang warehouse district — better lighting, more corporate energy",
        ],
        flavor_crowds   = [
            "Saints community members who know the contestants personally",
            "Iron Fang buyers looking for talent to recruit",
            "Argent Blades members who wandered in from next door and stayed",
        ],
        expire_hours    = 24,
        description     = "Open craft competition judged on quality, explanation, and durability. Patchwork Saints community event with Iron Fang prize sponsorship.",
    ),

    CompetitionType(
        slug           = "talent",
        name           = "Open Talent Show",
        sponsors       = ["Patchwork Saints"],
        format         = "judged",
        skill_pillars  = ["Performance", "Acrobatics", "Sleight of Hand", "Animal Handling"],
        phases         = [
            RoundPhase("The Act",          "Three minutes. Whatever discipline the contestant chose.",        "Performance",      12),
            RoundPhase("Crowd Reaction",   "Read the room and adjust the finish accordingly.",                "Insight",          13, advantage_if_prev_won=True),
            RoundPhase("Judge's Question", "The panel asks one unexpected question. Improv required.",        "Persuasion",       14, advantage_if_prev_won=True),
        ],
        rounds_bracket  = 1,
        contestants_min = 3,
        contestants_max = 16,
        npc_factions    = ["Patchwork Saints", "Independent", "Adventurers Guild"],
        reward_ec_base  = 150,
        reward_ec_final = 1_000,
        kharma_per_win  = 20,
        flavor_venues   = [
            "the Saints' open courtyard in the Warrens — mismatched chairs, genuine warmth",
            "the Pilgrim's Rest main hall — cleared out for the night",
            "Collapsed Plaza outdoor stage — weather permitting, which it never does",
        ],
        flavor_crowds   = [
            "Warrens residents of every species, all ages — the Saints' core community",
            "a few off-duty adventurers who heard there was free food",
            "Mara the Scrapper in the back row with extremely strong opinions about the scoring",
        ],
        expire_hours    = 24,
        description     = "No category restrictions. Any skill, any act. Patchwork Saints community event. Judges are three randomly selected Warrens residents.",
    ),

]

# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

_BY_SLUG: dict[str, CompetitionType] = {ct.slug: ct for ct in COMPETITION_TYPES}


def get_competition_type(slug: str) -> Optional[CompetitionType]:
    return _BY_SLUG.get(slug)


def list_competition_types() -> List[CompetitionType]:
    return list(COMPETITION_TYPES)
