"""
Build WotC-format module.html for both Saturday modules using structured data.
Scene count is determined per-story — not hardcoded.

Run: python scripts/build_modules_saturday.py
"""
import sys
sys.path.insert(0, "c:/Users/akodoreign/Desktop/chatGPT-discord-bot")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import zipfile
import shutil
from pathlib import Path
from src.mission_builder.html_renderer import render_module_structured

OUT = Path("generated_modules")
OUT.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# STORY BEAT ANALYSIS — Corrupted Divine Contract
#
# Novel beats identified:
#   1. Entry into hostile territory (Serpent's Maw) — approach + intel
#   2. Sub-level with rival/informant (Gilded Fang) — complication before vault
#   3. Main discovery + boss fight (Vault of Khyron) — climax
#   4. Moral decision with Lirien Vex — second climax / pivot
#   5. Consequence scene with Veyra + loose end (Kael) — resolution
#
# Story has TWO climax beats (the fight + the choice) → needs 5 scenes.
# Skipping sub-beats: Kael Veyth could fold into scene 2 OR get its own scene.
# Decision: keep separate — players often split on this encounter. 5 scenes.
# ─────────────────────────────────────────────────────────────────────────────

CONTRACT = {
    "title": "Unraveling the Corrupted Divine Contract",
    "faction": "Serpent Choir",
    "tier": "Major",
    "cr": 6,
    "party_level": 5,
    "runtime": "3-4 hours",
    "players": "4-6",
    "hook": (
        "High Priestess Veyra Mournveil sends for you through a Choir intermediary. "
        "When you arrive at her alcove in the Sanctum Quarter, she does not stand. "
        "She slides a map across the table without greeting you. "
        "'The Divine Contract is unraveling. Its glyphs have been corrupted — the Obsidian Veil infiltrated us. "
        "The ritual to complete the corruption begins at midnight. You have until then to recover the relic and stop it. "
        "The Serpent's Maw. Beneath the bazaar. The Veil's sanctum is there.' "
        "She meets your eyes. 'Do not alert the Choir's leadership. I do not know who else is compromised.'"
    ),
    "hook_note": (
        "Real situation: the Contract's corruption was deliberate — a Choir member is trying "
        "to break the binding on Khyron, the god sealed inside it. Veyra suspects but will "
        "not say it directly. Let players discover this through play, not exposition.\n"
        "Time pressure: the ritual completes at midnight. Every 30-minute delay in-game "
        "advances the ritual phase. Use this to create urgency without forcing a chase."
    ),
    "scenes": [
        {
            "num": 1,
            "name": "THE SERPENT'S MAW ENTRANCE",
            "beat_label": "Approach / Intel",
            "read_aloud": (
                "The Maw opens before you like a throat — narrow alleys choked with merchant stalls, "
                "lanterns casting jagged light over racks of serpent skins, venom vials, and things "
                "that watch you from their cages. The air is spiced and rotten in equal measure. "
                "Somewhere ahead, past the first bend, the alleys split into a dozen directions and "
                "all of them look the same. A merchant in a patterned robe is watching you. "
                "He has been watching since you entered."
            ),
            "gm_note": (
                "Two approaches to the sanctum: through the main bazaar (social, slower, more info) "
                "or through a maintenance shaft on Veyra's map ('compromised but navigable').\n"
                "The Veil patrol rotates every 15 minutes — if players spend too long with Kael, "
                "they'll have to deal with the patrol regardless."
            ),
            "npcs": [
                {
                    "name": "Kael the Scaleseller",
                    "role": "merchant, Veil-adjacent, opportunist",
                    "wants": "to not get caught in whatever is about to happen",
                    "knows": "the Veil's patrol schedule; the Serpent's Heart gemstone is the ritual focus; "
                             "the tapestry marked 'Scales of Justice' hides the passage down",
                    "hides": "he already sold information about the party to the Veil — a runner left 10 minutes ago",
                    "branches": [
                        "If players approach openly: he quotes 50 EC. DC 14 Persuasion: talks free + reveals patrol route. "
                        "DC 12 Intimidation: same result but he sends a second runner. Paying 50 EC: no runner sent.",
                        "If players ask about the ritual: 'Midnight. Central chamber. They're not destroying it — "
                        "merging it with something else. I don't know what.' DC 15 Insight: he's leaving something out. "
                        "Push him → admits a Choir member is helping from inside.",
                        "If players examine his ledger (DC 14 Investigation or just ask): a sketch of a serpent "
                        "with a human face — the Choir's historical traitor symbol. Clue A.",
                        "If players do nothing and walk past: he trails them at distance, watching. The patrol finds them first.",
                    ],
                },
            ],
            "mechanics": [
                "DC 13 Stealth (group check) to bypass Veil patrol entirely. On failure: one enforcer stops party. "
                "DC 14 Persuasion or DC 12 Deception to talk past him. On second failure: combat.",
                "DC 14 Investigation of the tapestry passage: fresh footprints, multiple people, recent. Clue B.",
            ],
            "clues": [
                "Clue A (free — just examine the ledger): Kael's serpent-with-human-face sketch = historical traitor symbol",
                "Clue B (DC 14 Investigation, tapestry): fresh footprints going down, Choir pendant dropped near entrance",
                "Clue C (pay Kael or DC 14 Persuasion): patrol schedule reveals a 4-minute gap in the eastern rotation",
            ],
            "stat_blocks": [
                {
                    "name": "Obsidian Veil Enforcer",
                    "count": 3,
                    "size_type": "Medium humanoid, lawful evil",
                    "ac": "15 (scale mail)",
                    "hp": "38 (6d8+12)",
                    "speed": "30 ft.",
                    "stats": "STR 13 (+1) | DEX 14 (+2) | CON 14 (+2) | INT 10 (+0) | WIS 11 (+0) | CHA 10 (+0)",
                    "skills": "Perception +4, Stealth +5",
                    "senses": "passive Perception 14",
                    "cr": "1 (200 XP each)",
                    "actions": [
                        "**Multiattack.** Two attacks: dagger or whip.",
                        "**Dagger.** +4 to hit, reach 5 ft. Hit: 1d4+2 piercing.",
                        "**Whip.** +4 to hit, reach 10 ft. Hit: 1d4+2 bludgeoning; target pushed 5 ft.",
                        "**Serpent's Breath (1/rest).** 15-ft. cone, DC 13 CON save or 2d6 poison + poisoned 1 minute.",
                    ],
                    "tactics": "Engage at whip range. Serpent's Breath if party clusters. "
                               "Leader (highest HP) retreats to warn the Hierophant when reduced below 10 HP.",
                    "if_lose": "Enforcers bind the party and deliver them to the Hierophant. "
                               "They wake in the sanctum — gear nearby but searched. Ritual is 30 minutes further along.",
                },
            ],
            "transition": (
                "The tapestry passage leads down. The air gets warmer. The faint sound of "
                "chanting rises from below — not loud, not distant. It sounds like something "
                "reading a name aloud very slowly."
            ),
        },
        {
            "num": 2,
            "name": "THE GILDED FANG",
            "beat_label": "Complication / Second Intel",
            "read_aloud": (
                "Below the main bazaar, the market continues in the dark. Stalls lit by "
                "bioluminescent fungi sell things the surface market won't touch. A merchant "
                "with a serpent coiled around his forearm watches your feet as you enter — "
                "not your face, your feet. He's counting how many of you there are. "
                "The chanting is closer here, behind a sealed iron door at the far end. "
                "And on the wall beside the door: a brass gong, freshly polished."
            ),
            "gm_note": (
                "Kael Veyth is NOT Obsidian Veil — he's an independent contractor playing both sides. "
                "His real name is Veyth; 'Kael' is a cover chosen to obscure his affiliation.\n"
                "The gong is a trap for impatient players. If struck: DC 14 WIS save or stunned 1 round "
                "AND the Hierophant starts the final ritual phase 10 minutes early.\n"
                "Iron door: DC 14 Thieves' Tools, DC 15 Strength to force, or key from patrol leader in Area 1."
            ),
            "npcs": [
                {
                    "name": "Kael Veyth",
                    "role": "independent broker, using 'Kael' as cover — not the same man as Area 1",
                    "wants": "to sell the Contract to the highest bidder after the ritual completes",
                    "knows": "the ritual's true purpose: merging the Contract with a forbidden eldritch pact, not destroying it",
                    "hides": "he is not Veil — his gear is non-standard if examined (DC 14 Insight immediately)",
                    "branches": [
                        "DC 14 Insight on sight: gear is not Veil-standard. If confronted: admits freelancer status.",
                        "Will share ritual's true purpose for 200 EC or DC 16 Persuasion: "
                        "'They're not destroying the Contract. They're marrying it to something older. "
                        "The Choir's god goes free. What's bound comes unbound.'",
                        "If combat starts: uses Scout stats, flees at half HP through a hidden side passage. "
                        "His serpent familiar stays to guard his ledger. The ledger has the ritual schedule and the Hierophant's name.",
                        "If players do nothing: Veyth approaches them. He wants buyers — he'll make the first move.",
                    ],
                },
            ],
            "mechanics": [
                "Gong (Environmental Hazard): DC 14 WIS save or stunned 1 round + ritual advances 10 minutes.",
                "Kael Veyth's ledger (on his person or in side passage if he fled): "
                "contains ritual schedule, Hierophant's name, and entry 'K. confirmed — Contract will hold.'",
                "The 'K.' in the ledger does not match Veyra (V). DC 14 Investigation to notice the initial.",
            ],
            "clues": [
                "Clue A (Kael Veyth's admission): ritual is a merger, not destruction — frees what's inside",
                "Clue B (ledger): entry 'K. confirmed' — a Choir member arranged this; initial is K, not V",
                "Clue C (DC 13 Arcana on the iron door glyphs): wards designed to keep something IN, not keep intruders out",
            ],
            "stat_blocks": [
                {
                    "name": "Kael Veyth",
                    "size_type": "Medium humanoid (human), neutral",
                    "ac": "13 (leather armor)",
                    "hp": "27 (6d8)",
                    "speed": "30 ft.",
                    "stats": "STR 11 (+0) | DEX 14 (+2) | CON 11 (+0) | INT 13 (+1) | WIS 11 (+0) | CHA 13 (+1)",
                    "skills": "Deception +5, Perception +4, Stealth +6, Survival +4",
                    "senses": "passive Perception 14",
                    "cr": "1/2 (100 XP) — flees; rarely fights to the death",
                    "actions": [
                        "**Multiattack.** Two attacks with shortsword.",
                        "**Shortsword.** +4 to hit, reach 5 ft. Hit: 1d6+2 piercing.",
                        "**Hand Crossbow.** +4 to hit, range 30/120 ft. Hit: 1d6+2 piercing.",
                    ],
                    "tactics": "Opens with Hand Crossbow from range. At half HP, uses Cunning Action (Disengage) "
                               "to retreat through the hidden side passage and seal it behind him.",
                    "if_lose": "He surrenders immediately at 0 HP rather than die for the job. "
                               "Will trade any information for his life.",
                },
            ],
            "transition": (
                "The iron door opens onto a short corridor. The chanting resolves into words — "
                "old Choir liturgy, but the rhythm is wrong. Inverted. Something is being "
                "released, not called."
            ),
        },
        {
            "num": 3,
            "name": "THE VAULT OF KHYRON",
            "beat_label": "Discovery / Boss Fight",
            "read_aloud": (
                "The vault is a perfect circle. At its centre, on a raised dais, the Divine "
                "Contract pulses — its pages gold one moment, ash the next, the glyphs on its "
                "surface writhing like something alive trying to read them from the inside. "
                "Before it stands a statue of a coiled serpent twenty feet tall, carved from "
                "a single block of obsidian, its eyes twin pools of molten gold. "
                "The eyes track you as you enter. The Hierophant is still chanting. "
                "The statue has not moved. But it is deciding."
            ),
            "gm_note": (
                "The statue does not engage unless party: (a) attacks the ritual, (b) moves within 10 ft. "
                "of the Contract, or (c) attacks the Hierophant. It is not mindless — it waits.\n"
                "Serpent's Heart: the gemstone in the statue's chest. Destroying it (AC 12, HP 15, any damage) "
                "removes Legendary Resistance and the Corrupted Glyph reaction.\n"
                "Key discovery: DC 18 Arcana/Religion, or reading the Contract's glyphs (no check if players "
                "approach it and describe examining the text): Khyron is INSIDE the Contract. "
                "The corruption is Khyron testing the binding from within. This is not a power source — it is a prison."
            ),
            "npcs": [
                {
                    "name": "The Hierophant",
                    "role": "Obsidian Veil ritual leader — gaunt, obsidian mask, shifting-scale face tattoos",
                    "wants": "the ritual to complete; will sacrifice anything, including themselves",
                    "knows": "the Contract's true nature; who the Choir traitor is (will not share willingly)",
                    "hides": "the Veil does not fully control what they are releasing — this concerns even him",
                    "branches": [
                        "DC 18 Persuasion to halt the ritual (he genuinely believes the release is necessary).",
                        "DC 14 Deception to stall for one round. On any failure: signals the statue and continues.",
                        "If players reveal that Khyron is conscious inside: DC 16 Persuasion to create doubt. "
                        "Success — Hierophant pauses, disbelieving but uncertain. One round to act.",
                        "If Hierophant reduced to 0 HP: ritual stops immediately. He dies at the dais, "
                        "whispering 'It was supposed to be different.'",
                    ],
                },
            ],
            "mechanics": [
                "DC 18 Arcana or Religion — or approaching and reading the Contract glyphs: "
                "Khyron is imprisoned inside. The corruption is him testing the seal.",
                "Serpent's Heart (chest gem): AC 12, HP 15, any damage type. "
                "Destroying it: statue loses Legendary Resistance + Corrupted Glyph reaction.",
                "Battlefield — Vault of Khyron: 60-ft. diameter circle. "
                "Raised dais (10-ft. radius, 5 ft. high) at center. "
                "Statue occupies center; immobile until triggered. "
                "Stone pillars at 4 compass points provide half cover. "
                "Lighting: pulsing gold from the Contract (bright light 20 ft., dim 40 ft.).",
            ],
            "clues": [
                "Clue A (DC 18 Arcana or reading glyphs): Khyron is inside — prison, not artifact",
                "Clue B (Hierophant's notes on the dais — visible): 'K. confirmed — Contract will hold long enough'",
                "Clue C (serpent pendant from Area 1 matched to vault portrait): the Choir traitor is identified",
            ],
            "stat_blocks": [
                {
                    "name": "The Veil's Guardian",
                    "size_type": "Huge construct, unaligned",
                    "ac": "19 (natural armor)",
                    "hp": "120 (16d8+48)",
                    "speed": "0 ft. (immobile until triggered)",
                    "stats": "STR 21 (+5) | DEX 11 (+0) | CON 16 (+3) | INT 3 (−4) | WIS 10 (+0) | CHA 1 (−5)",
                    "saves": "DEX +4, WIS +4",
                    "skills": "Perception +4",
                    "resistances": "acid, lightning, necrotic",
                    "immunities": "fire (vulnerability), charmed, exhaustion, frightened, grappled, prone",
                    "senses": "darkvision 60 ft., passive Perception 14",
                    "cr": "6 (2,300 XP)",
                    "traits": [
                        "**False Appearance.** While motionless, indistinguishable from an ordinary statue.",
                        "**Legendary Resistance (3/Day).** Can choose to succeed on a failed saving throw. "
                        "(Lost if Serpent's Heart destroyed.)",
                    ],
                    "actions": [
                        "**Multiattack.** Two attacks: Maw and Tail.",
                        "**Maw.** +8 to hit, reach 10 ft. Hit: 21 (3d8+5) piercing. "
                        "DC 14 CON save or charmed 1 minute (charmed creature attacks nearest ally on its turn).",
                        "**Tail.** +8 to hit, reach 15 ft. Hit: 17 (2d8+5) bludgeoning + target knocked prone.",
                        "**Corrupted Glyph (Reaction).** When a creature within 30 ft. makes an attack roll, "
                        "impose disadvantage on that roll. (Lost if Serpent's Heart destroyed.)",
                    ],
                    "tactics": "Opens with Corrupted Glyph to protect Hierophant's concentration. "
                               "Targets heaviest armor first. At half HP: focuses on whoever is nearest the Contract. "
                               "Fire damage removes Vulnerability immunity — watch for fire spells.",
                    "if_lose": "Statue restrains the party. Hierophant binds them as witnesses. "
                               "They wake after ritual completion — Khyron has been released. "
                               "The Warrens have a new instability. Lirien Vex is standing over them.",
                },
            ],
            "transition": (
                "The statue falls or stands aside. The Contract pulses on the dais, waiting. "
                "A hidden panel in the vault wall has slid open. Lirien Vex is standing in it, "
                "watching, and she begins to clap. Once. Twice. Three times."
            ),
        },
        {
            "num": 4,
            "name": "LIRIEN VEX AND THE CHOICE",
            "beat_label": "Moral Pivot",
            "read_aloud": (
                "She applauds three times. Obsidian mask. Silver tattoos up both arms. "
                "A staff with a serpent's head, inert for now. 'You found it,' she says. "
                "'You understand what it is. Most people get this far and still think they're "
                "here to retrieve a relic.' She tilts her head. "
                "'What are you going to do with that?'"
            ),
            "gm_note": (
                "Lirien Vex is NOT the villain. She arranged for the party to be here — she tipped "
                "off the Choir through Veyra's handler to ensure someone capable would show up and "
                "make a real decision. She cannot destroy the Contract herself: it requires an act "
                "of genuine will, not ritual.\n"
                "She was a Choir member herself, twenty years ago. She will not volunteer this. "
                "DC 16 History or DC 15 Insight if she lets something slip.\n"
                "Three outcomes — do NOT push toward any of them. This is the players' call."
            ),
            "npcs": [
                {
                    "name": "Lirien Vex",
                    "role": "Veil agent, true agenda: she wants the Contract destroyed on the party's terms",
                    "wants": "someone to destroy the Contract properly — she cannot do it alone",
                    "knows": "the ritual is a trap; the traitor's identity; Khyron has been conscious for decades",
                    "hides": "she was a Choir member herself, years ago",
                    "branches": [
                        "If players attack: 'That will not help you decide.' She does not retaliate for 1 round. "
                        "DC 14 Insight: she is deliberately not retaliating. If they persist: Mage stats, "
                        "summons serpent swarm (CR 3) as distraction, retreats through hidden passage. "
                        "Leaves a note: 'Destroy it. Ask it what it wants to be.'",
                        "If players ask what they should do: 'The Contract is alive. Whatever is bound inside "
                        "has been alive the whole time. The question is whether what comes out is what was "
                        "put in, or what two hundred years of imprisonment made it.'",
                        "If players ask about the traitor: 'The letter K. Kael the Scaleseller. "
                        "Choir for thirty years. He wanted Khyron freed long before the Veil got involved.'",
                        "If players do nothing — wait her out: she waits back. She is patient. "
                        "Eventually: 'Midnight approaches. The decision becomes less yours the longer you wait.'",
                    ],
                },
            ],
            "what_happens": [
                "**Option A — Destroy the Contract:** Speak the old Choir liturgy correctly (DC 15 Religion, "
                "or Lirien tells them the words if asked sincerely). Contract dissolves. Khyron's essence disperses — "
                "not destroyed, scattered. The Choir loses its divine bond. The Warrens stabilise. Veyra will grieve. Party gains Discretion Bonus.",
                "**Option B — Preserve the Contract:** Choir's power survives. Khyron remains bound but is now awake "
                "and testing more aggressively. Within months the Contract will need reinforcing. The party bought time, not a solution.",
                "**Option C — Free Khyron deliberately (complete the ritual):** Khyron manifests — a fragment of divine power, not the whole god. "
                "He does not attack. He looks at whoever freed him and asks: 'Why?' "
                "Whatever the party answers becomes the foundation of a future relationship with a freed god.",
                "**If players do nothing:** Midnight arrives. The ritual completes on its own. Option C by default — "
                "but Khyron's first words are to Lirien, not the party. He knows who made the choice.",
            ],
            "mechanics": [
                "DC 15 Religion to speak the correct Choir liturgy for Option A.",
                "DC 20 Arcana (alternative to Religion) — raw magical understanding of what the glyphs need.",
                "DC 14 Insight on Lirien: she is being completely honest. No manipulation.",
                "DC 16 History or DC 15 Insight if Lirien slips: she was Choir, twenty years ago.",
            ],
            "clues": [
                "Clue A (Lirien volunteers): Kael the Scaleseller — Choir for thirty years, arranged the Veil access",
                "Clue B (pendant from Area 1 matched to Hierophant's notes): the 'K.' in the ledger is Kael",
                "Clue C (Lirien, if asked about the liturgy): 'Speak what you want it to become, not what it is.'",
            ],
            "transition": (
                "Whatever the party decides at the dais, the panel Lirien came through leads back up. "
                "Kael the Scaleseller is probably already running."
            ),
        },
        {
            "num": 5,
            "name": "RESOLUTION AND FALLOUT",
            "beat_label": "Resolution",
            "read_aloud": (
                "Veyra receives you in the same alcove where she hired you. "
                "She reads your faces before you speak. The serpent pendant around her neck — "
                "Choir standard issue — shifts when you mention Kael's name. 'Kael,' she says. "
                "How long have you known? Not angry. Tired in a specific way that suggests "
                "she is accounting for something she already suspected."
            ),
            "gm_note": (
                "Veyra KNEW Kael was involved. She did not know the extent. She is deciding whether to admit this.\n"
                "DC 14 Insight: she is relieved, not surprised. The Contract's fate matters less than the traitor named.\n"
                "DC 15 Persuasion for the real answer: 'If I told you Kael was involved and you found him first, "
                "he would have told you I knew. I needed you to find it yourselves so the evidence was yours, not mine.'\n"
                "Kael: if party gave chase — DC 15 Perception to catch him in the bazaar. "
                "If caught, he talks immediately. His motive was genuine faith, not malice."
            ),
            "npcs": [
                {
                    "name": "Veyra Mournveil",
                    "role": "High Priestess, Serpent Choir — exhausted, accountable, still in control",
                    "wants": "to know exactly what happened and whether her faith survives the night",
                    "knows": "more than she said when she hired you",
                    "hides": "she suspected Kael; her silence was tactical, not ignorance",
                    "branches": [
                        "If players present evidence cleanly: she nods once, authorises payment, asks one question: "
                        "'Did he believe it was right?' Whatever the party answers — she closes her eyes.",
                        "If players confront her about withholding: DC 15 Persuasion for the full truth. "
                        "She does not apologise. 'You were effective. That is what I needed.'",
                        "If Option C was chosen (Khyron freed): Veyra goes still. Long pause. "
                        "'Then the Choir is... changed.' She still pays. But she does not say goodbye.",
                    ],
                },
            ],
            "mechanics": [
                "DC 14 Insight on Veyra: she already knew about Kael — she is relieved, not surprised.",
                "DC 15 Persuasion to get Veyra's full admission about why she withheld Kael's name.",
                "Kael chase (if applicable): DC 15 Perception in the bazaar. "
                "Combat: Scout stats + 1 Warlock level (Eldritch Blast). "
                "If caught at 0 HP: surrenders immediately and explains his faith.",
            ],
            "what_happens": [
                "**Contract destroyed (Option A):** 200 EC + 150 Kharma base. Discretion Bonus +200 EC. "
                "Evidence Bonus +300 EC + scroll 'Divine Contract: A History' (if Kael's ledger recovered). "
                "Serpent Choir rep +1 tier. Aldric Ebonwhisper unlocked as contact.",
                "**Contract preserved (Option B):** 200 EC + 100 Kharma. No bonus. "
                "Choir rep +1 but Veyra is privately disappointed.",
                "**Khyron freed (Option C):** Veyra still pays base reward — obligation. "
                "Choir rep neutral (she will not punish them, but the relationship is complicated). "
                "Khyron's 'Why?' is now in the campaign's permanent record. The Warrens have a new instability.",
                "**Failed (ritual completed without party input):** Choir rep −1. Veyra exiles them. "
                "Kael escapes. The Warrens have a new instability. Future bulletins will reflect Khyron's presence.",
            ],
            "transition": (
                "Regardless of outcome: Khyron is now a thing the campaign knows about. "
                "Whether he is scattered, bound, or free — he was conscious inside that Contract. "
                "That does not end when the session does."
            ),
        },
    ],
    "rewards": (
        "**Base:** 200 EC + 150 Kharma per player\n"
        "**Discretion Bonus** (+200 EC): resolve without alerting Choir leadership beyond Veyra\n"
        "**Evidence Bonus** (+300 EC + uncommon scroll): recover Kael's ledger, present it to Veyra with traitor ID'd\n"
        "**Faction:** Serpent Choir reputation +1 tier; access to Veyra's private archive\n"
        "**Unlock:** Aldric Ebonwhisper as future contact for artifact jobs\n"
        "**Lirien Vex** becomes a recurring figure — her agenda is not fully resolved\n"
        "**Failure:** Choir rep −1. Veyra exiles party. Kael escapes."
    ),
    "dc_table": [
        ["Area", "Check", "DC", "Success", "Failure"],
        ["1", "Persuasion (Kael Scaleseller)", "14", "Info + no warning", "Info + runner sent"],
        ["1", "Insight (hiding something)", "15", "Choir insider exists", "Take info at face value"],
        ["1", "Stealth (bypass patrol, group)", "13", "Avoid entirely", "Confrontation"],
        ["1", "Investigation (tapestry)", "14", "Footprints + Choir pendant", "Find passage, miss clues"],
        ["2", "Insight (Kael Veyth affiliation)", "14", "Not Veil gear", "Trust him as Veil"],
        ["2", "Persuasion (ritual truth)", "16", "Merger, not destruction", "He withholds"],
        ["3", "Arcana/Religion (Contract)", "18", "Khyron is inside", "Reads as corrupted power source"],
        ["3", "Persuasion (halt Hierophant)", "18", "He hesitates", "Ritual continues"],
        ["3", "Persuasion (Hierophant w/evidence)", "16", "Creates doubt — one round pause", "He signals statue"],
        ["4", "Religion (correct liturgy)", "15", "Contract dissolves cleanly", "Nothing happens — try again"],
        ["4", "Insight (Lirien honest)", "14", "Completely truthful", "Uncertain"],
        ["5", "Insight (Veyra knew)", "14", "She already knew", "Seems genuinely surprised"],
        ["5", "Persuasion (Veyra full truth)", "15", "She explains the withholding", "She deflects"],
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# STORY BEAT ANALYSIS — Heart of the First Flame
#
# Novel beats identified:
#   1. Outer Wall Approach — entry, Iron Fang tension, first context  [approach]
#   2. The Ashen Hollow — 7-alcove puzzle, guardian, first fragment   [investigation]
#   3. The Iron Fang Cisterns — Gavrel, second fragment, Council hook [complication]
#   4. The Warden's Ritual — Tessara, corruption choice, third frag   [second climax]
#   5. The Sanctum Filing — close the record, Council acknowledgement [resolution]
#
# Story has two distinct climax beats (guardian fight + Tessara's ritual)
# and three fragment MacGuffins that must each get proper attention.
# Merging any two would rush the fragments — keeping 5 is correct here.
# ─────────────────────────────────────────────────────────────────────────────

FLAME = {
    "title": "Heart of the First Flame",
    "faction": "Iron Fang Consortium",
    "tier": "Major",
    "cr": 6,
    "party_level": 5,
    "runtime": "3-4 hours",
    "players": "4-6",
    "hook": (
        "The Iron Fang Consortium's job board carries a sealed commission: a relic survey "
        "of the Outer Wall complex at Sector 7-Bravo, believed to be a decommissioned wardens' post. "
        "The Iron Fang wants confirmation the site is clear and the old wards are inactive. "
        "The pay is unusually good for a survey job. "
        "The contact, Darro, meets you at the checkpoint. He doesn't make eye contact. "
        "'The Consortium's interests in this site are archival,' he says. 'That's all you need to know.'"
    ),
    "hook_note": (
        "Real situation: The site contains the Warden's Sanctum — a pre-Consortium record-keeping "
        "facility for tracking champions. Three fragments of a Flame Relic are sealed inside, "
        "each protected by a guardian tied to the old Warden order.\n"
        "The Culinary Council is watching this site. They have been waiting for someone to "
        "open the Sanctum record and close it properly — triggering a formal acknowledgement "
        "of the party's legend-point threshold (15 LP, above the 7+ interference threshold).\n"
        "Darro genuinely does not know the full truth. He's following orders from an Iron Fang "
        "tier above his clearance."
    ),
    "scenes": [
        {
            "num": 1,
            "name": "OUTER WALL APPROACH",
            "beat_label": "Approach / Tension",
            "read_aloud": (
                "The Outer Wall complex at Sector 7-Bravo is older than the Iron Fang's records. "
                "The stone is the wrong color — not the Consortium's pale grey but something darker, "
                "pre-industrial, carved rather than poured. The checkpoint gate is open. "
                "The Iron Fang scouts who were supposed to be here are not. "
                "Their gear is stacked neatly against the wall, like someone asked them to leave it. "
                "Darro stops walking."
            ),
            "gm_note": (
                "The scouts weren't harmed — they were compelled to leave their gear and go home. "
                "The old ward magic doesn't hurt people; it redirects them. This should unsettle, not alarm.\n"
                "Darro: DC 12 Insight — he is more frightened than he's showing. He knows something. "
                "DC 14 Persuasion to get it: 'The Consortium found references to a guardian system in the site records. "
                "Active, not dormant. They told me it was decommissioned.' He was lied to.\n"
                "The relic dossier pulses stronger as party approaches the gate. "
                "Someone in the party who has handled relics before feels it pull forward and down."
            ),
            "npcs": [
                {
                    "name": "Darro",
                    "role": "Iron Fang mid-tier liaison — young, over his clearance level, frightened",
                    "wants": "to complete the survey without anything going wrong",
                    "knows": "the Iron Fang found references to a guardian system; was told it was decommissioned",
                    "hides": "he was explicitly told not to share the guardian reference with the survey party",
                    "branches": [
                        "DC 12 Insight on sight: more frightened than he's showing.",
                        "DC 14 Persuasion: admits the guardian system reference; he was told to withhold it.",
                        "If players refuse to enter without full information: Darro buckles at DC 12 Persuasion. "
                        "He gives everything he has — which isn't much.",
                        "Darro will not enter the complex beyond the checkpoint. He waits outside.",
                    ],
                },
            ],
            "mechanics": [
                "DC 13 Investigation of the scouts' gear: nothing missing, no signs of struggle — "
                "gear removed voluntarily, placed neatly. Clue A.",
                "DC 14 Arcana on the gate carvings: old Warden-order script. Translation (DC 16): "
                "'Those who enter in service are witnessed. Those who enter in greed are turned back.' Clue B.",
                "Relic dossier (if party has it): pulses with increasing intensity. "
                "A character who has handled relics before feels it pull forward and slightly down — beneath them.",
            ],
            "clues": [
                "Clue A (Investigation, scouts' gear): gear removed voluntarily — the ward doesn't harm, it redirects",
                "Clue B (DC 14-16 Arcana on gate): old Warden script — entering in service is witnessed; greed is turned back",
                "Clue C (Darro w/ DC 14 Persuasion): guardian system is active, not decommissioned — Consortium lied",
            ],
            "transition": (
                "The gate stays open. The ward didn't turn you back. Whatever the old system is "
                "checking for, you passed. The passage ahead slopes down, and the darkness "
                "at the bottom is not empty — there is something faintly luminous about it."
            ),
        },
        {
            "num": 2,
            "name": "THE ASHEN HOLLOW",
            "beat_label": "Investigation / First Fragment",
            "read_aloud": (
                "The chamber at the bottom of the passage was cut — not formed naturally. "
                "The floor is perfectly flat under three centuries of ash. Seven alcoves are "
                "carved into the far wall, each containing a different object: a quill, a coin, "
                "a broken chain, a small mirror, a candle (unlit), a folded cloth, and in the "
                "rightmost alcove, a sealed glass vial holding a liquid that has begun moving "
                "toward you the moment you stepped inside. It is tracking someone in the party."
            ),
            "gm_note": (
                "The seven alcoves are a lock. The puzzle is about intention, not mechanics. "
                "The Warden order tested champions by asking what they valued, then checking "
                "whether they were honest about it.\n"
                "Correct answer: each object represents a champion quality. The party must "
                "take the object that represents why they are ACTUALLY here — not the idealized version. "
                "If they take the coin (profit) and they're genuinely mercenary, the lock opens. "
                "If they take the quill (record/knowledge) out of pretense, nothing happens.\n"
                "The guardian is not hostile unless the party tries to force the lock or destroy alcoves. "
                "It is old, patient, and watching."
            ),
            "npcs": [
                {
                    "name": "The Ashen Warden",
                    "role": "construct-guardian, dormant in the ash — activates if lock is forced or alcoves damaged",
                    "wants": "the lock to be solved correctly — it doesn't want to fight",
                    "knows": "which champion quality each object represents; whether the party's intention matches their choice",
                    "hides": "nothing; it is incapable of deception",
                    "branches": [
                        "If party takes the correct object for their true reason: lock opens, Warden "
                        "does not activate. The first fragment appears in the rightmost alcove where the vial was.",
                        "If party takes the wrong object (self-deception): nothing happens. Warden still dormant. "
                        "The ash settles. They can try again.",
                        "If party forces the lock or damages an alcove: Warden activates. It will fight until the "
                        "party retreats to the passage mouth — then it stops and waits.",
                        "If party defeats the Warden in combat: first fragment appears. "
                        "But a second Warden manifests in Area 3 instead of the normal guardian.",
                    ],
                },
            ],
            "mechanics": [
                "DC 13 History: the Warden order used object-choice puzzles to assess champion motivation.",
                "DC 15 Insight on the vial's movement: it's tracking the party member who carries the most "
                "unresolved intention about why they took this job.",
                "Object choices and what they represent: Quill (knowledge/record), Coin (profit/material), "
                "Broken Chain (freedom/justice), Mirror (self/truth), Candle (hope/service), "
                "Cloth (protection/compassion), Vial (the job itself — this is correct for pure mercenaries).",
                "DC 14 Religion: the alcove system is a Warden sacrament called 'the honest accounting.' "
                "It cannot be gamed — only answered.",
            ],
            "clues": [
                "Clue A (DC 13 History): Warden-order puzzles test honest intention, not clever answers",
                "Clue B (DC 15 Insight): the vial tracks the party member with the most unresolved 'why'",
                "Clue C (DC 14 Religion): the honest accounting — it cannot be gamed, only answered truthfully",
            ],
            "stat_blocks": [
                {
                    "name": "The Ashen Warden",
                    "size_type": "Large construct, lawful neutral",
                    "ac": "16 (natural armor)",
                    "hp": "85 (10d10+30)",
                    "speed": "30 ft.",
                    "stats": "STR 18 (+4) | DEX 10 (+0) | CON 16 (+3) | INT 10 (+0) | WIS 14 (+2) | CHA 8 (−1)",
                    "saves": "STR +7, CON +6",
                    "immunities": "charmed, exhaustion, frightened, paralyzed, poison",
                    "senses": "darkvision 60 ft., passive Perception 12",
                    "cr": "5 (1,800 XP)",
                    "traits": [
                        "**Warden's Purpose.** The Warden stops fighting and returns to dormancy if all party members "
                        "retreat to the passage mouth. It does not pursue beyond the chamber.",
                        "**Ash Shroud.** When the Warden takes 15+ damage in a single hit, it releases a cloud of "
                        "ash (10-ft. radius, DC 13 CON save or blinded until end of next turn).",
                    ],
                    "actions": [
                        "**Multiattack.** Two Slam attacks.",
                        "**Slam.** +7 to hit, reach 10 ft. Hit: 14 (2d8+4) bludgeoning.",
                        "**Ashen Grasp (Recharge 5-6).** One creature within 10 ft., DC 14 STR save or "
                        "restrained and taking 9 (2d8) necrotic damage at the start of each of its turns. "
                        "DC 14 STR check (action) to break free.",
                    ],
                    "tactics": "Focuses on whoever most recently touched an alcove object. "
                               "Uses Ashen Grasp on the party's highest-damage dealer. "
                               "Never chases beyond the chamber mouth.",
                    "if_lose": "The Warden does not kill. At 0 HP, it collapses into ash and the first fragment "
                               "appears in the rightmost alcove. A second Warden will manifest in Area 3.",
                },
            ],
            "transition": (
                "The first fragment is warm in whoever holds it — not hot, warm. Like something "
                "that has been waiting in the cold for a very long time and is glad to be held. "
                "A passage on the east wall, previously sealed, has opened. The sound from beyond "
                "it is running water."
            ),
        },
        {
            "num": 3,
            "name": "THE IRON FANG CISTERNS",
            "beat_label": "Complication / Second Fragment",
            "read_aloud": (
                "The cisterns are enormous — a vaulted chamber the size of a small district, "
                "dry now but built to hold enough water to supply the entire Outer Wall complex. "
                "The Iron Fang has been here before you. Survey markers are bolted into the far wall. "
                "A beacon device has been placed at the centre of the chamber, activated. "
                "It is broadcasting a signal on the Iron Fang survey frequency. "
                "Gavrel is standing next to it. He sees you the moment you see him."
            ),
            "gm_note": (
                "Gavrel: Iron Fang senior surveyor — not malicious, genuinely competitive. "
                "He triggered the beacon as soon as he found the second fragment, following protocol. "
                "The signal has been broadcasting for approximately 20 minutes. "
                "This means Iron Fang leadership now knows the site is active and occupied.\n"
                "Second fragment: sealed in a case mounted to the east wall — accessible via DC 14 "
                "Thieves' Tools, DC 16 Strength (pry it off), or Gavrel's keycard (he has it).\n"
                "Culinary Council reveal: Gavrel found a symbol etched in the stone near the fragment case — "
                "a pomegranate inside a flame. He doesn't know what it means. The party might."
            ),
            "npcs": [
                {
                    "name": "Gavrel",
                    "role": "Iron Fang senior surveyor — methodical, ambitious, not hostile",
                    "wants": "to secure the fragment for the Consortium and get credit for finding it first",
                    "knows": "the beacon has been broadcasting 20 minutes; Iron Fang management is en route; "
                             "the pomegranate-flame symbol near the case; his keycard opens the mount",
                    "hides": "he's not sure the Consortium's intentions for this site are archival anymore",
                    "branches": [
                        "DC 13 Persuasion: he acknowledges the party's claim and agrees to share access, "
                        "provided they're logged as co-discoverers in the survey report.",
                        "DC 15 Persuasion: he hands over the keycard entirely — in exchange for the party "
                        "filing the Consortium's report rather than an outside report.",
                        "If players threaten: Gavrel presses the beacon twice — distress signal. "
                        "Iron Fang response team arrives in 15 minutes (combat if still on-site).",
                        "If players explain what the site actually is (Warden sanctum, active guardians): "
                        "Gavrel's competitive certainty wobbles. DC 12 Persuasion — he becomes cooperative.",
                    ],
                },
            ],
            "mechanics": [
                "Second fragment mount: DC 14 Thieves' Tools, DC 16 Strength to pry, "
                "or Gavrel's keycard (negotiate or acquire).",
                "Pomegranate-flame symbol (DC 14 History or Religion): mark of the Culinary Council's observer network. "
                "It means this site is watched. It means the Council knows the party is here.",
                "Beacon broadcast: 20 minutes active. Iron Fang response team en route. "
                "Every 10 minutes the party stays, another layer of Consortium personnel is notified.",
                "DC 14 Investigation of the cistern walls: older etchings beneath the Iron Fang survey markers — "
                "Warden record-symbols. The cistern is part of the Sanctum complex, not separate from it.",
            ],
            "clues": [
                "Clue A (visible — Gavrel points it out): pomegranate-flame symbol near the fragment case",
                "Clue B (DC 14 History/Religion on symbol): Council observer mark — this site is watched",
                "Clue C (DC 14 Investigation of walls): cistern IS part of the Sanctum — the whole complex is the record",
            ],
            "transition": (
                "Two fragments. One more somewhere above — the dossier pull has shifted: "
                "up, and slightly south. The Warden who gave them this much without a fight "
                "must have had a reason. The pomegranate symbol on the wall didn't appear by accident."
            ),
        },
        {
            "num": 4,
            "name": "THE WARDEN'S RITUAL",
            "beat_label": "Climax / Third Fragment",
            "read_aloud": (
                "The ritual chamber is at the top of a spiral stair that wasn't on any Iron Fang survey. "
                "The walls are lined with names — carved, not painted — thousands of them, "
                "in columns so fine they must have taken generations to complete. "
                "At the far end, a figure in pale robes is kneeling before an altar, "
                "hands pressed flat to the stone. She is not praying. She is listening. "
                "She turns her head slowly. 'You brought both fragments,' she says. "
                "'Good. I have been waiting approximately forty years for someone to do that.'"
            ),
            "gm_note": (
                "Tessara: the last active Warden. Not dangerous unless the party attacks. "
                "She has been maintaining the ritual that keeps the third fragment pure — "
                "if she stops, the fragment becomes corrupted and useless within hours.\n"
                "She knows about the Culinary Council. She is not afraid of them. "
                "'They have been watching this site since before the Iron Fang existed.' "
                "She will not say more about them unless the party demonstrates 15+ LP.\n"
                "The third fragment requires purification — the party must touch all three "
                "fragments together on the altar. This takes 10 minutes and requires stillness. "
                "During this time, Tessara maintains the ward. If interrupted (combat, disruption), "
                "the ritual must restart."
            ),
            "npcs": [
                {
                    "name": "Tessara",
                    "role": "last active Warden — ancient, tired, quietly relieved",
                    "wants": "the record to be closed correctly and the fragments to leave with someone worthy",
                    "knows": "everything about the Sanctum's history; the Council's symbol; why the party is here",
                    "hides": "she is not as old as she looks — the Sanctum's ward magic preserves her; she would have died decades ago otherwise",
                    "branches": [
                        "If players ask about the Culinary Council: 'They observe champions. They have been "
                        "watching this site since it was built. The pomegranate and flame is their oldest mark.' "
                        "No more without evidence of LP threshold.",
                        "If players demonstrate 15+ LP (faction rep, notable deeds, or the party's record): "
                        "Tessara nods slowly. 'Then the Council will have already noticed you. "
                        "What happens next is not mine to say — but they will reach out when they are ready.'",
                        "If party attacks: Tessara does not fight. She releases the ward — the third fragment "
                        "begins corrupting immediately. 'You have approximately one hour before it's slag.' "
                        "She walks out through a door that seals behind her.",
                        "If party rushes the ritual (tries to cut the 10 minutes short): "
                        "the purification fails. All three fragments must be re-attuned. Add 10 more minutes.",
                    ],
                },
            ],
            "mechanics": [
                "Purification ritual: all three fragments on the altar, held by party members, 10 minutes of stillness. "
                "Any combat or major disruption resets the timer.",
                "DC 15 Religion during the ritual: party member feels the Warden-ward extend over them briefly — "
                "not protective, observational. Something is watching the ritual and approving.",
                "DC 14 History on the name-wall: the Warden order kept records of every champion they observed. "
                "Some names are recognizable from Undercity history. One column is blank — reserved.",
                "If Iron Fang response team arrives (from Area 3): Tessara seals the stair behind the party. "
                "'You have your ten minutes. I will give them to you.'",
            ],
            "clues": [
                "Clue A (Tessara directly): Council has observed this site since it was built — oldest mark",
                "Clue B (DC 15 Religion during ritual): the ward briefly extends and observes — approval",
                "Clue C (DC 14 History on name-wall): the blank column is reserved — for who is not written",
            ],
            "transition": (
                "All three fragments unite on the altar. For a moment the chamber is very bright. "
                "Then quiet. Tessara opens a small drawer in the altar and takes out an envelope — "
                "sealed with wax pressed into the shape of a pomegranate. "
                "She holds it out to whoever is nearest. 'This is not from me.'"
            ),
        },
        {
            "num": 5,
            "name": "THE SANCTUM FILING",
            "beat_label": "Resolution / Council Acknowledgement",
            "read_aloud": (
                "The envelope contains a single folded card. The handwriting is extremely neat. "
                "'Your record has been opened in the First Flame index. "
                "We have been patient. So have you, although you did not know you were waiting. "
                "When the time is appropriate, a representative will make contact. "
                "Do not look for us. We find.' No signature. No faction mark. "
                "Only a small pressed pomegranate flower attached to the bottom corner."
            ),
            "gm_note": (
                "This is the Council's first direct acknowledgement. Not a summons, not a demand — "
                "a notice. The party is above the 7+ LP threshold and the Council has now formally "
                "acknowledged their existence in the First Flame index (a record that predates the Consortium).\n"
                "Darro is still waiting at the checkpoint. His survey report will credit the party. "
                "The Iron Fang response team is at the bottom of the stairs, confused — "
                "Tessara's ward simply redirected them. They'll file an 'access denied' report.\n"
                "The three purified fragments: what to do with them. Tessara will not say where they go. "
                "'That is the next question. It is yours, not mine.' She sits back down at the altar."
            ),
            "npcs": [
                {
                    "name": "Tessara",
                    "role": "at the altar — she has done what she came to do; she is not leaving",
                    "wants": "for the party to understand what they are holding and take it seriously",
                    "knows": "where the fragments should ultimately go, but will not say — it's not her record to write",
                    "hides": "she is staying in the Sanctum permanently; she is the last ward, not just its keeper",
                    "branches": [
                        "If party asks where the fragments go: 'That is your question now. The record says you are "
                        "champions. Champions decide what the flame is for.'",
                        "If party asks if she's coming with them: 'No. I am the record.' "
                        "She gestures at the name-wall. 'When you are done, yours will be there too.'",
                        "If party asks about the Council letter: 'I have been holding that letter for eleven years. "
                        "I was told to give it when the right champions came. You are the first who got this far.'",
                    ],
                },
            ],
            "what_happens": [
                "**Complete the Sanctum filing:** Tessara's record formally closes. "
                "Party's names are added to the name-wall. The Sanctum is now sealed — "
                "the Iron Fang survey will return 'access denied' from now on.",
                "**Keep the fragments:** the party now holds three purified Flame Relics. "
                "Their use, storage, and significance is a future story question.",
                "**Sell the fragments (Iron Fang):** Darro's report files clean. "
                "200 EC bonus from the Consortium. Tessara does not comment. "
                "The Council's letter still arrived — the record is already written.",
                "**Destroy the fragments:** Tessara watches without expression. "
                "'That is also a decision.' The Council letter still arrived. "
                "The blank column on the name-wall gets one entry.",
            ],
            "mechanics": [
                "Darro's survey report: party can dictate what goes in it. "
                "Truth version: the Consortium gains nothing and the site is sealed. "
                "Consortium version: 200 EC bonus, but Iron Fang now has a record of the site being 'cleared.'",
                "Pomegranate envelope: the letter is genuine Council correspondence. "
                "DC 18 Arcana: the wax seal is imbued — whoever broke it was observed in that moment.",
                "Iron Fang response team (if Darro sent distress signal in Area 3): they emerge from the stairs, "
                "disoriented. They can be managed diplomatically (DC 14 Persuasion) or the party can simply leave.",
            ],
            "transition": (
                "The ward turns the lights down as you leave — not off, just lower. "
                "Tessara is still at the altar. The blank column on the name-wall has two new entries. "
                "Darro is at the checkpoint, reading his survey instruments, pretending he hasn't been "
                "watching the gate for the last two hours."
            ),
        },
    ],
    "rewards": (
        "**Base:** 150 EC + 125 Kharma per player (Iron Fang survey rate)\n"
        "**Consortium Bonus** (+200 EC): file the Iron Fang's version of the survey report\n"
        "**Fragment Bonus** (variable): Tessara gives no guidance — the value of the relics depends on what the party does with them\n"
        "**Council Acknowledgement:** The First Flame index now has the party's record open. This is not a reward — it is a status change.\n"
        "**Faction:** Iron Fang Consortium rep +1 (survey completed); Wardens of Ash rep +1 (if party respected the sanctum)\n"
        "**Unlock:** Future Council contact is now possible. The blank column on the name-wall has room."
    ),
    "dc_table": [
        ["Area", "Check", "DC", "Success", "Failure"],
        ["1", "Insight (Darro scared)", "12", "More frightened than showing", "Seems merely nervous"],
        ["1", "Persuasion (Darro, guardian info)", "14", "Admits guardian system is active", "He deflects to orders"],
        ["1", "Arcana (gate carvings)", "14-16", "Warden script + translation", "Old carvings, unknown origin"],
        ["2", "History (alcove puzzle)", "13", "Warden honest-accounting sacrament", "Decorative alcoves"],
        ["2", "Insight (vial tracking)", "15", "Tracks most unresolved intention", "It's just moving"],
        ["2", "Religion (honest accounting)", "14", "Cannot be gamed — only answered", "A test of some kind"],
        ["3", "Persuasion (Gavrel, share access)", "13", "Co-discoverer credit", "He holds the keycard"],
        ["3", "Persuasion (Gavrel, keycard)", "15", "He hands it over", "Files his report first"],
        ["3", "History/Religion (pomegranate symbol)", "14", "Council observer mark", "Unknown faction symbol"],
        ["4", "Religion (during purification)", "15", "Feel the ward observe and approve", "Just warmth and stillness"],
        ["4", "History (name-wall)", "14", "Record of observed champions — blank column reserved", "Historical names"],
        ["5", "Arcana (envelope seal)", "18", "Imbued — Council observed whoever broke it", "Expensive wax"],
        ["5", "Persuasion (Iron Fang team)", "14", "They leave peacefully", "They file a disruption report"],
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# BUILD
# ─────────────────────────────────────────────────────────────────────────────

def build_contract():
    html = render_module_structured(CONTRACT)
    path = OUT / "Corrupted_Divine_Contract_module.html"
    path.write_text(html, encoding="utf-8")
    print(f"Contract module: {path.name} ({path.stat().st_size // 1024}KB, "
          f"{len(CONTRACT['scenes'])} areas)")


def build_flame():
    flame_dir = OUT / "Heart_of_the_First_Flame_20260425_191859"
    flame_dir.mkdir(exist_ok=True)
    html = render_module_structured(FLAME)
    path = flame_dir / "module.html"
    path.write_text(html, encoding="utf-8")
    print(f"Flame module: {path.name} ({path.stat().st_size // 1024}KB, "
          f"{len(FLAME['scenes'])} areas)")

    # Rebuild ZIP
    zip_path = OUT / "Heart_of_the_First_Flame_20260425_191859.zip"
    existing = list(flame_dir.iterdir())
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in existing:
            zf.write(f, arcname=f"Heart_of_the_First_Flame_20260425_191859/{f.name}")
    print(f"Flame ZIP rebuilt: {zip_path.name} ({zip_path.stat().st_size // 1024}KB)")


if __name__ == "__main__":
    build_contract()
    build_flame()
    print("\nBoth modules ready for Saturday.")
