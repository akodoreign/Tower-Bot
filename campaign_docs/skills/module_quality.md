# Skill: Mission Module Quality Standards
**Keywords:** module, mission, one-shot, adventure, generate, document, docx, scene, encounter, stat block, NPC, boss, combat, investigation, session, DM, play, run, write
**Category:** style
**Version:** 1
**Source:** seed

## Purpose
This skill governs how the bot generates D&D 5e 2024 mission module documents. It fixes systematic quality issues identified in early generated modules and establishes standards based on official WotC one-shot structure and community best practices.

---

## THE DRAGONLANCE PIPELINE — Two Products, One Story

Every mission generates **two separate documents** for two separate audiences. Confusing them is the #1 source of bad output.

### THE NOVEL (BobAgent — 5-10 chapters)
- **Audience:** DM only. Players NEVER see it.
- **Purpose:** Fixed-protagonist story that establishes NPCs, locations, dialogue hooks, and plot beats.
- **Format:** Prose chapters with named characters and fixed outcomes.
- **Analogy:** The Dragonlance Chronicles novels — Tanis, Flint, and Raistlin have fixed roles. The DM reads them for source material.
- **Length:** 5-10 chapters. NOT 20. 20 chapters = a campaign arc, not a session.

### THE MODULE (BookToModuleAgent — 5 scenes)
- **Audience:** Party of 4-6 players. This is the actual game product.
- **Purpose:** Same story events, but the party plays through them their own way.
- **Format:** 5 numbered areas (WotC format). Generic 4-6 players. CR pulled from party level.
- **NOT character-specific.** Boxxo may appear as an NPC in the novel — the module doesn't stat out Boxxo's abilities. It stats the enemies.
- **Analogy:** DL1 Dragons of Despair — canonical events, but how the PCs interact is open.
- **Reference:** https://en.wikipedia.org/wiki/List_of_Dragonlance_modules_and_sourcebooks

### Dynamic Scene Count (beat analysis first, THEN write)

Scene count is determined by the story, not by convention. Before writing anything:

1. **List every distinct story beat** in the novel source: approach, investigation locations, complications, climax(es), moral pivots, resolution.
2. **Count the beats. That is your scene count.** If two beats can share a scene without rushing, merge them.
3. **Label each scene** before writing it: `[Approach]` `[Intel]` `[Investigation]` `[Complication]` `[Pivot]` `[Climax]` `[Choice]` `[Resolution]`

| Beat count | Scenes | Runtime | Story type |
|-----------|--------|---------|------------|
| 3 | 3 | ~2 hrs | Linear — heist, rescue, delivery |
| 4 | 4 | ~2.5 hrs | One mid-story complication |
| 5 | 5 | ~3-4 hrs | Two climax beats (fight + moral choice) |
| 6 | 6 | ~4-5 hrs | Multi-faction, competing agendas |
| 7 | 7 | 5+ hrs | Campaign-weight — use sparingly |

**If two scenes share the same label → merge them. If a beat has no scene → cut the beat.**

Common beat sequence (not mandatory):
- Hook/Approach — party learns situation, first NPC contact
- Investigation — main puzzle or discovery location
- Complication — reveal, ambush, something changes
- Climax — main confrontation or decision point
- Resolution — consequences, rewards, next hook

**One session = one module. If you have 8+ scenes, you have two sessions.**

---

## CRITICAL ISSUES TO FIX (from analysis of generated modules)

### 1. READ-ALOUD Abuse
**Problem:** Everything is wrapped in 📖 READ ALOUD blocks — DM notes, skill check instructions, shopping lists, even meta-commentary like "Pacing: Allow the party to spend some time..."
**Rule:** READ ALOUD blocks are ONLY for atmospheric text the DM reads to players. Maximum 3-4 sentences per block. DM Notes, skill checks, NPC motivations, and mechanical instructions are NEVER read aloud. Use clear formatting labels: `📖 READ ALOUD:` for player-facing text, `🎲 MECHANICS:` for game rules, `📝 DM NOTES:` for DM-only information.

### 2. Name Inconsistency
**Problem:** Boss is called "Commander Veridia" in narrative but "Commander Valthoria" in the stat block. NPC "Moros" in scene text becomes "Ezekiel Blackthorn" in stats. "Lord Blackhand" appears in stats but never in the story.
**Rule:** Every NPC name MUST be identical between narrative text and stat block. Before outputting the stat block section, re-read the narrative to confirm names match exactly.

### 3. Scene Flow & Pacing
**Problem:** Modules have 12+ scenes crammed into a 2-hour runtime. Investigation acts have 4-6 locations that would each take 20+ minutes to run, totaling 2 hours for Act 2 alone.
**Rule:** A 2-hour module supports 5-7 total scenes maximum. Structure:
- Act 1 (Briefing): 1-2 scenes, ~20 minutes. Get players the job and out the door FAST.
- Act 2 (Investigation/Exploration): 2-3 scenes, ~40 minutes. Maximum 3 investigation locations, not 6.
- Act 3 (Climax): 1-2 scenes, ~45 minutes. The main encounter.
- Resolution: 1 scene, ~15 minutes. Rewards, consequences, hooks.

### 4. Missing Enemy Statistics
**Problem:** Scenes reference "a group of assassins," "armed thugs," or "Eira Ironsteel" without providing combat statistics inline. Stats appear in appendices (if at all) and sometimes under different names.
**Rule:** EVERY creature the party might fight MUST have a stat block. Place stat blocks immediately after the scene where the creature appears — not in appendices. Use the standard 5e 2024 stat block format.

### 5. Overly Complex Plots
**Problem:** A 2-hour module involves infiltrating the Tower of Last Chance, outsmarting the FTA, fighting through multiple guard layers, confronting a boss, AND exposing a multi-faction conspiracy. This is a 6-session campaign arc compressed into one session.
**Rule:** One-shot plots follow: Simple Goal + One Complication + Climax. The goal should be explainable in one sentence. "Find out who's sabotaging the Wardens' supply chain" not "uncover a multi-layered conspiracy involving four factions, three artifacts, and a divine prophecy."

### 6. Repetitive Structure
**Problem:** Every module opens at The Soot & Cinder, visits the same 3 intel locations (Guild of Ashen Scrolls, Glass Sigil, Patchwork Saints), uses the same vendor setup, and follows the identical Act structure.
**Rule:** Vary meeting locations based on the contracting faction. Wardens meet at the Outer Wall guardhouse. Obsidian Lotus meets in a hidden basement. Argent Blades meet at the Arena. Intel locations should be relevant to the specific plot, not generic faction hubs.

### 7. NPC Quality Over Quantity
**Problem:** Modules list 4-6 NPCs with motivations and secrets, but none have combat stats. Players meet them once and never see them again. Secret motivations are revealed to the DM but never become relevant in the 2-hour runtime.
**Rule:** Maximum 3-4 named NPCs per module. Each NPC MUST serve a clear mechanical purpose: quest-giver, informant, obstacle, or enemy. If an NPC has a secret, that secret MUST be discoverable during play and MUST affect the outcome.

### 8. Missing Tactical Information
**Problem:** Combat encounters describe enemies but don't explain the battlefield. No cover, no elevation, no hazards, no movement constraints.
**Rule:** Every combat encounter MUST include:
- A text description of the battlefield (3-4 sentences)
- A bullet list of tactical features: cover positions, difficult terrain, elevation, interactable objects, lighting
- Enemy tactics: what they do on round 1, what they do when bloodied, when they flee/surrender
- What happens if the party is losing (escape route, mercy, capture)

---

## THE CORRECT MODULE STRUCTURE

### Three-Act Structure (for ~2 hour sessions)

**Act 1: The Hook (15-20 minutes, 1-2 scenes)**
Purpose: Get the players invested and moving.
- Scene 1: The Contract — who's hiring, what's the job, why NOW
  - One READ ALOUD paragraph setting the scene (3-4 sentences)
  - NPC dialogue (2-3 key lines, not a monologue)
  - What the NPC knows vs. what they reveal
  - Answer to the obvious player questions (Why us? What's the pay? What's the danger?)
- Scene 2 (optional): Quick Prep — ONE location for gathering intel or buying supplies
  - Not three locations. Pick the ONE most interesting/relevant one.
  - Include a rumor or clue that foreshadows the complication

**Act 2: The Adventure (50-60 minutes, 2-3 scenes)**
Purpose: The core gameplay — exploration, investigation, roleplay, minor combat.
- Each scene has: Location description, what's here, what players can do, what they learn, transition to next scene
- Include ONE skill challenge OR minor combat encounter (not both unless the module is 3+ hours)
- Include ONE meaningful choice that affects Act 3
- All paths lead forward — no dead ends, no red herrings that waste time

**Act 3: The Climax (30-40 minutes, 1-2 scenes)**
Purpose: The payoff — the main combat encounter or dramatic confrontation.
- The Boss/Main Encounter with full stat blocks inline
- Battlefield with tactical features
- Clear victory and defeat conditions
- At least one non-combat resolution option (surrender, negotiation, clever use of earlier information)

**Resolution (10-15 minutes, 1 scene)**
- Success, failure, and partial success outcomes
- Reward distribution
- 2-3 hooks for future adventures (brief, 1-2 sentences each)

---

## STAT BLOCK STANDARDS

### Format (D&D 5e 2024)
```
**[Name]** *(Size Type, Alignment)*
AC [value] ([source])
HP [value] ([hit dice])
Speed [value]
STR [score] ([mod]) | DEX | CON | INT | WIS | CHA
Saving Throws: [proficient saves with bonuses]
Skills: [proficient skills with bonuses]
Damage Resistances: [if any]
Senses: [darkvision X ft., passive Perception X]
Languages: [languages]
CR [value] ([XP])

**[Trait Name].** [Description]

**Actions**
**[Attack Name].** *[Melee/Ranged] Weapon Attack:* +[bonus] to hit, reach [X] ft., one target. *Hit:* [damage dice + mod] [type] damage.

**[Special Action Name] (Recharge X-6).** [Description with save DC, damage, area, duration]
```

### Balance Guidelines
- Moderate DC = CR + 8 (e.g., CR 6 = DC 14)
- Hard DC = CR + 10 (e.g., CR 6 = DC 16)
- Boss HP = approximately 15 × CR (e.g., CR 6 boss ≈ 90 HP)
- Boss AC = 13-16 depending on armor
- Minion HP = 3-5 × their CR
- Boss should have Legendary Resistance at CR 8+
- Boss should have 1 signature ability that makes them memorable
- Attack bonus should be proficiency + relevant ability mod (typically +5 to +8 for CR 4-8)

### Required Creatures Per Module
- 1 Boss/Leader (CR = module CR)
- 2-4 Minions (CR = module CR ÷ 2 to CR ÷ 4)
- 1 Optional environmental hazard or trap (with detection DC, trigger, effect, and damage)

---

## SCENE FORMAT TEMPLATE

**CRITICAL: Header format is `N - LOCATION NAME` (ALL CAPS). NEVER "Scene N:" or "### Scene N:".**

```
N - LOCATION NAME

Read this:
  [Italicized. 2-4 atmospheric sentences — sight, sound, smell.
   MUST end with something requiring player response. Not a statement — a hook.]

NPC NAME — role
- Wants: [specific to this scene, concrete]
- Knows: [plot-relevant facts they will share]
- Hides: [what they conceal and why]

If players ask about [X]: [response + DC]
  On success DC N Skill: [exact info revealed]
  On failure: [consequence — never a dead end]
If players do nothing: [scene advances anyway — world is not on pause]

[Clue A / Clue B / Clue C structure — three independent paths to the critical conclusion]

[STAT BLOCK INLINE HERE — never in an appendix]
[Tactics: Round 1 behavior, when bloodied, when they flee/surrender]
[If players lose: escape route / capture / mercy clause]

TRANSITION: [Pulls players forward with a mystery or threat. NEVER "the party proceeds."]
```

**Examples:**
```
CORRECT: 3 - THE GILDED FANG
WRONG:   Scene 3: The Gilded Fang
WRONG:   ### Scene 3: The Gilded Fang
WRONG:   Act 2, Scene 3: The Gilded Fang
```

---

## INVESTIGATION MODULE SPECIFICS

For INVESTIGATION-type missions, replace combat-heavy Act 2 with a structured investigation:

### The Three-Clue Rule
Every critical conclusion the players need to reach must be supported by at least THREE independent clues pointing to it. If players miss one clue, they can still find the answer through the other two.

### Investigation Scene Structure
Each investigation location should give the players:
1. One confirmed fact (they get this automatically by visiting)
2. One hidden detail (requires a skill check to find)
3. One social opportunity (talking to someone reveals something)

### Time Pressure
Investigation modules MUST include a reason the players can't take forever:
- The target is leaving town at dawn
- The evidence will be destroyed
- Someone else is investigating and will get there first
- The next victim will be targeted tonight

---

## REWARD BALANCE

### Currency (per Tower of Last Chance economy)
- Local/Patrol (CR 4): 50-100 EC + 25-50 Kharma
- Standard/Escort (CR 5): 100-150 EC + 50-100 Kharma
- Investigation (CR 6): 100-200 EC + 50-100 Kharma
- Rift/Dungeon (CR 7-8): 200-400 EC + 100-200 Kharma

### Magic Items
- CR 4-5: 1 uncommon item (not both players get one — the party shares)
- CR 6-7: 1 uncommon + 1 common consumable
- CR 8-10: 1 rare OR 2 uncommon
- Never give items that break the campaign (no +2 weapons at CR 4)

### Faction Reputation
- Standard completion: +1 with contracting faction
- Bonus objective: +1 additional (stated up front so players know it exists)
- Failure: -1 with contracting faction, maybe +1 with opposing faction

---

## WHAT NOT TO DO (common LLM failures)

0. **Do NOT use "Scene N:" as a header.** The correct format is `N - LOCATION NAME` (ALL CAPS, number-dash-name). "Scene 1: The Ruined Market" is WRONG. "1 - THE RUINED MARKET" is CORRECT. This error is CRITICAL — it signals the entire module is formatted wrong.
0. **Do NOT put stat blocks in an appendix.** Inline, immediately after the scene where the creature appears.
0. **Do NOT write a 20-chapter novel and call it a module.** The module is 5 numbered areas. The novel can be 5-10 chapters and is separate — DM-only source material.
0. **Do NOT stat out player characters in the module.** The module is for generic 4-6 players. CR comes from party level. Boxxo/party members are NPCs in the story, not stat blocks in the module.
1. Do NOT have every NPC speak in the same dramatic, portentous tone. Vary speech patterns. A dwarf blacksmith talks differently than an Aasimar priestess.
2. Do NOT write "the city watches" or "whispers ripple through the streets" — these are empty filler.
3. Do NOT create false leads that waste player time. In a 2-hour session, every scene must advance the plot.
4. Do NOT make the Tower of Last Chance the dungeon location for every module. The Tower is the party's HOME BASE. Use other locations.
5. Do NOT invent new factions or gods not in the campaign lore. Use existing factions and NPCs from the roster.
6. Do NOT give quest-givers long monologues. 2-3 sentences of dialogue, then let the players ask questions.
7. Do NOT put shopping lists in READ ALOUD blocks.
8. Do NOT use "Eir Velan" as every quest-giver. Different factions have different contacts.
9. Do NOT write lore contradictions — check the NPC roster and faction data before assigning roles.
10. Do NOT give the boss more than 2 lair actions. One memorable ability > five forgettable ones.


---

## Self-Evaluation — 2026-04-26 01:20

**Module evaluated:** Heart_of_the_First_Flame_20260425_191859
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 4 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 4 (need ≥1 per combat scene)
- Skill checks / branches: 15 (need ≥5)
- GM NOTE boxes: 4 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 0 NPC truth element(s) — NPCs lack Wants/Knows/Hides structure

**Content gaps (LLM critique):**
- "The generated content is entirely CSS code with no actual scene text." - The entire module is CSS formatting, not gameplay content.
- "The CSS code contains no numbered location sections ("N - Area Name")" - Missing required numbered area headers.
- "The CSS code lacks any interaction mechanics or clue reveals." - No skill checks, NPC dialogue, or plot progression exists.


---

## Self-Evaluation — 2026-04-27 01:12

**Module evaluated:** Codex_in_the_Bone_Market_20260426_154710
**LLM quality score:** 1/10

**Structural counts (from real output):**
- READ ALOUD blocks: 6 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 4 (need ≥1 per combat scene)
- Skill checks / branches: 30 (need ≥5)
- GM NOTE boxes: 6 (need ≥3)
- Transitions: 8 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 2 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 1 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "/* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208; ..." - CSS code instead of numbered areas
- ".cover { background: linear-gradient(160deg, #1a1208 0%, #2e2010 60%, #1a1208 100%); color: #e8d9b4; padding: 72px 64px 56px; text-align: center; border-bottom: 8px solid var(--gold); position: relative; }" - Missing read-aloud blocks and scene numbering
- "/* ── Typography ────────────────────── */" - No conversation branches, stat blocks, or playable content


---

## Self-Evaluation — 2026-04-28 01:16

**Module evaluated:** The_Relics_Shadow_20260427_072950
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 6 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 4 (need ≥1 per combat scene)
- Skill checks / branches: 59 (need ≥5)
- GM NOTE boxes: 6 (need ≥3)
- Transitions: 8 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: 17 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 2 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- Missing numbered areas (entire content is CSS code instead of module content)
- No read-aloud blocks (CSS code lacks narrative scenes)
- No stat blocks (CSS code has no inline monster/NPC stats)


---

## Self-Evaluation — 2026-04-29 01:05

**Module evaluated:** The_Plows_Shadow_20260428_103010
**LLM quality score:** 2/10

**Structural counts (from real output):**
- READ ALOUD blocks: 6 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 4 (need ≥1 per combat scene)
- Skill checks / branches: 56 (need ≥5)
- GM NOTE boxes: 6 (need ≥3)
- Transitions: 8 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: 17 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- [READ_ALOUD_FORMAT] - "At the front desk, a smiling young woman welcomes the party." (missing sensory details and player response demand)
- [NUMBERED_AREAS] - "Scene 1 - Front Desk" (incorrect format; should be "1 - Front Desk")
- [INLINE_STAT_BLOCKS] - No stat blocks for combat encounters (required for playability)


---

## Self-Evaluation — 2026-04-30 01:08

**Module evaluated:** Purification_of_the_Hollow_Vein_20260429_190721
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 13 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 8 (need ≥1 per combat scene)
- Skill checks / branches: 4 (need ≥5)
- GM NOTE boxes: 13 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 4 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 4 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 1 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- Missing numbered areas - "── Cover ──" format instead of "1 - Area Name"
- No read-aloud blocks - "Cover { ... }" section lacks 2-4 sensory sentences
- No conversation branches - "Cover { ... }" has no NPC dialogue or player responses


---

## Self-Evaluation — 2026-05-01 01:19

**Module evaluated:** Three_Reagents_for_the_Hollow_Spire_20260430_104107
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 34 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 33 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- Missing module content (the entire generated text is CSS code, not adventure text)
- No numbered areas (the CSS code lacks any scene numbering format)
- No NPC dialogue or stat blocks (no playable elements exist in the generated text)


---

## Self-Evaluation — 2026-05-02 01:14

**Module evaluated:** Three_Reagents_for_the_Hollow_Spire_20260430_104107
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 34 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 33 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "Three Reagents for the Hollow Spire /* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208; ..." — The entire module is CSS code, not a D&D module with scenes, NPCs, or gameplay elements
- ".page { max-width: 900px; margin: 0 auto; background: var(--parchment); padding: 0 0 64px; box-shadow: 0 4px 24px rgba(0,0,0,
- 1); ..." — CSS styling code lacks any narrative or gameplay content


---

## Self-Evaluation — 2026-05-03 01:09

**Module evaluated:** Rescue_of_the_Shattered_Oath_20260502_183253
**LLM quality score:** 1/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 0 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 0 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- Missing read-aloud format: "The party enters the tower, its stone walls cold and damp..." (no sensory details or player action)
- Incorrect area numbering: "1 - Front Desk" (should be "1 - Front Desk" without the hyphen)
- No conversation branches: "Mayeda offers them a full stay..." (no "If players ask about X" branches)


---

## Self-Evaluation — 2026-05-04 01:15

**Module evaluated:** The_Plows_Shadow_20260503_152646
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "The Plow's Shadow /* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208;..." - The entire file is CSS code with no actual module content
- ".cover { background: linear-gradient(160deg, #1a1208 0%, #2e2010 60%, #1a1208 100%); color: #e8d9b4; padding: 72px 64px 56px; text-align: center; border-bottom: 8px solid var(--gold); position: relative; }" - No scene content exists in the CSS
- ".chapter-first-para::first-letter { float: left; font-size: 64px; line-height:


---

## Self-Evaluation — 2026-05-05 01:12

**Module evaluated:** The_Plows_Echo_20260504_124705
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 6 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 6 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "/* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208; ..." - Missing numbered areas and scene structure
- ".cover { background: ..." - No conversation branches or player response triggers
- "/* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208; ..." - No inline stat blocks or GM notes


---

## Self-Evaluation — 2026-05-06 01:25

**Module evaluated:** Blight_in_the_Scrap_Yards_20260505_102008
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 7 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 8 (need ≥1 per combat scene)
- Skill checks / branches: 4 (need ≥5)
- GM NOTE boxes: 7 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 4 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 4 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 1 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "/* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208;..." - Missing numbered scenes and narrative content entirely
- ".cover { background: linear-gradient(160deg, #1a1208 0%, #2e2010 60%, #1a1208 100%); color: #e8d9b4; padding: 72px 64px 56px; text-align: center; border-bottom: 8px solid var(--gold);" - CSS code instead of scene setup
- "hr { border: none; background: linear-gradient(to right, transparent, var(--gold) 20%, var(--gold) 80%, transparent); height: 2px; margin: 36px 0; }" - CSS code instead of skill check mechanics


---

## Self-Evaluation — 2026-05-07 01:19

**Module evaluated:** Relic_Retrieval_from_the_Warrens_20260506_094311
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 32 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 32 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 1 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "/* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208; ..." - The entire content is CSS code instead of module text
- ".page { max-width: 900px; margin: 0 auto; background: var(--parchment); padding: 0 0 64px; box-shadow: 0 4px 24px rgba(0,0,0,
- 25); border: 1px solid var(--rule); }" - No actual module content exists


---

## Self-Evaluation — 2026-05-08 01:22

**Module evaluated:** Cult_Stronghold_Infiltration_20260507_132149
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 7 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 6 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "Cult Stronghold Infiltration /* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208; ..." - The entire file is CSS code with no gameplay content
- ".page { max-width: 900px; margin: 0 auto; background: var(--parchment); padding: 0 0 64px; box-shadow: 0 4px 24px rgba(0,0,0,
- 25); border: 1px solid var(--rule); }" - CSS styling code with no gameplay content


---

## Self-Evaluation — 2026-05-09 01:14

**Module evaluated:** Iron_Pits_Cache_Raid_20260508_170246
**LLM quality score:** 0/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "/* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root { --ink: #1a1208;" - The entire module is CSS code with no narrative content
- ".page { max-width: 900px; margin: 0 auto; background: var(--parchment); padding: 0 0 64px; box-shadow: 0 4px 24px rgba(0,0,0,
- 25); border: 1px solid var(--rule); }" - CSS styling without any adventure content


---

## Self-Evaluation — 2026-05-09 01:14

**Module evaluated:** Iron_Pits_Cache_Raid_20260508_170246
**LLM quality score:** 1/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "/* ── Tower of Last Chance — Mission Module Stylesheet ────────────────────── */ :root {" - Missing actual module content entirely
- ".cover { background: linear-gradient(160deg, #1a1208 0%, #2e2010 60%, #1a1208 100%); color: #e8d9b4; padding: 72px 64px 56px; text-align: center; border-bottom: 8px solid var(--gold); position: relative; }" - CSS styling without narrative content
- "table { width: 100%; border-collapse: collapse; margin: 24px 0 28px; font-size: 15px; box-shadow: 0 1px 4px rgba(0,0,0,


---

## Self-Evaluation — 2026-05-10 01:18

**Module evaluated:** Defense_of_the_Veiled_Path_20260509_165105
**LLM quality score:** 2/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 11 (need ≥5)
- GM NOTE boxes: 1 (need ≥3)
- Transitions: 3 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 GM NOTE(s) — need ≥3 for a 3-scene module
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 11 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 2 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- "The CSS code lacks any narrative or scene descriptions" — the entire content is CSS styling with no module text
- "The CSS code uses 'N - Name' format but contains no actual area descriptions or content" — the numbered areas are empty
- "The CSS code ends with a table tag" — the incomplete HTML tag indicates missing content


---

## Self-Evaluation — 2026-05-11 01:13

**Module evaluated:** Defense_of_the_Veiled_Path_20260509_165105
**LLM quality score:** 4/10

**Structural counts (from real output):**
- READ ALOUD blocks: 0 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 1 (need ≥4)
- Inline stat blocks: 2 (need ≥1 per combat scene)
- Skill checks / branches: 11 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No READ ALOUD blocks — players have no atmospheric immersion text
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: 1 stat block(s) placed in appendix — must be INLINE immediately after NPC/monster introduction in the scene
- LOW: 11 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 2 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- **READ_ALOUD_FORMAT** - "Location: The underground meeting hall is a vast chamber..." lacks sensory descriptions and player response cues (fails 1-2 criteria)
- **INLINE_STAT_BLOCKS** - "Lurking Snakes Attackers entering this area..." has no monster stats (fails 4 criteria)
- **FAILURE_CONSEQUENCES** - "DC 14 Nature check" lacks failure consequences (fails 8 criteria)


---

## Self-Evaluation — 2026-05-12 01:20

**Module evaluated:** The_Leaden_Crowns_Corruption_20260511_091657
**LLM quality score:** 3/10

**Structural counts (from real output):**
- READ ALOUD blocks: 14 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 16 (need ≥1 per combat scene)
- Skill checks / branches: 0 (need ≥5)
- GM NOTE boxes: 14 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 0 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: 1 stat block(s) placed in appendix — must be INLINE immediately after NPC/monster introduction in the scene
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 1 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- Missing conversation branches for NPCs ("If players ask about X" branches absent in all rooms)
- Stat blocks not inline ("Carrion Crawler Hatchling" stat block is in an appendix, not after monster description)
- No failure consequences for DCs ("DC 14 Persuasion" has no failure clause)


---

## Self-Evaluation — 2026-05-13 01:20

**Module evaluated:** Codex_Smoke_Infestation_20260507_105406_20260507_105406
**LLM quality score:** 3/10

**Structural counts (from real output):**
- READ ALOUD blocks: 10 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 8 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 10 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- [NUMBERED_AREAS] "R01 Pump Room Entry" — should be "1 - Pump Room Entry" (incorrect format)
- [INLINE_STAT_BLOCKS] "Monster Roster Variants (weakest → strongest)" — stat blocks must be inline with monster appearances, not in a separate section
- [CONVERSATION_BRANCHES] "Monsters light: 1 rot grub" — no NPC dialogue branches or player interaction mechanics


---

## Self-Evaluation — 2026-05-14 01:09

**Module evaluated:** Codex_Smoke_Infestation_20260507_105406_20260507_105406
**LLM quality score:** 3/10

**Structural counts (from real output):**
- READ ALOUD blocks: 10 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 8 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 10 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- [NUMBERED_AREAS] "R01 Pump Room Entry" uses incorrect format - should be "1 - Pump Room Entry"
- [INLINE_STAT_BLOCKS] Monster stat blocks are in separate section - should be inline with room descriptions
- [CONVERSATION_BRANCHES] No NPC dialogue branches - missing "If players ask about X" handling


---

## Self-Evaluation — 2026-05-15 01:20

**Module evaluated:** Codex_Smoke_Infestation_20260507_105406_20260507_105406
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 10 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 8 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 10 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-18 01:18

**Module evaluated:** The_Shattered_Oath_20260517_135331
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 0 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 0 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No READ ALOUD blocks — players have no atmospheric immersion text
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 0 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-19 01:12

**Module evaluated:** The_Shattered_Oath_20260517_135331
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 0 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 0 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No READ ALOUD blocks — players have no atmospheric immersion text
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 0 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-21 01:16

**Module evaluated:** The_Weight_of_the_Crown_20260520_071045
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 0 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 34 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No READ ALOUD blocks — players have no atmospheric immersion text
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 33 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-22 01:14

**Module evaluated:** The_Iron_Scar_Contract_20260521_062218
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 7 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 8 (need ≥1 per combat scene)
- Skill checks / branches: 3 (need ≥5)
- GM NOTE boxes: 6 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 3 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: 1 stat block(s) placed in appendix — must be INLINE immediately after NPC/monster introduction in the scene
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-24 01:10

**Module evaluated:** The_Iron_Scar_Contract_20260521_062218
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 7 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 8 (need ≥1 per combat scene)
- Skill checks / branches: 3 (need ≥5)
- GM NOTE boxes: 6 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- LOW: Only 3 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- CRITICAL: 1 stat block(s) placed in appendix — must be INLINE immediately after NPC/monster introduction in the scene
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-25 01:10

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-26 01:11

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-27 01:18

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-28 01:18

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-29 01:17

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-30 01:16

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-05-31 01:17

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-01 01:16

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-02 01:16

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-03 01:16

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-04 01:16

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-05 01:15

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-06 01:15

**Module evaluated:** Shattered_Sigil_Reckoning_id1157_20260524_192638_198
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 3 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 6 (need ≥1 per combat scene)
- Skill checks / branches: 1 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 3 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- LOW: Only 1 skill check/conversation branch(es) — need ≥5 (min 2 per NPC)
- LOW: Only 0 'If players ask' conversation branch(es) — NPCs need ≥2 branches each. DMs cannot improvise social encounters without them.
- LOW: 1 skill check DC(s) but NO failure consequences specified — every DC must say what happens when players fail
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: Only 0 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Only 0 NPC truth element(s) — NPCs need explicit Wants/Knows/Hides
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-07 01:14

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-08 01:15

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-09 01:15

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-09 03:35

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-10 01:15

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-11 01:17

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-11 01:24

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-12 01:19

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-12 01:21

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified


---

## Self-Evaluation — 2026-06-12 01:24

**Module evaluated:** Veyra_Maws_Silent_Ledger_id1276_20260606_152714_182
**LLM quality score:** 5/10

**Structural counts (from real output):**
- READ ALOUD blocks: 1 (need ≥4 per 5-scene module)
- Numbered areas (N - Name): 0 (need ≥4)
- Inline stat blocks: 0 (need ≥1 per combat scene)
- Skill checks / branches: 21 (need ≥5)
- GM NOTE boxes: 0 (need ≥3)
- Transitions: 0 (need ≥4)

**Format failures this run:**
- LOW: Only 1 READ ALOUD block(s) — need ≥4 for a 3-scene module
- CRITICAL: No numbered areas (e.g. '1 - Front Desk') — locations are not scannable
- MISSING: No GM NOTE boxes — DMs have no private guidance during scenes
- CRITICAL: No stat blocks — enemies cannot be run in combat
- LOW: 14 DC(s) but only 1 failure consequence(s) — most skill checks leave DMs guessing what failure means
- LOW: Only 0 transition(s) — scenes don't lead into each other
- LOW: 1 weak transition(s) using 'the party proceeds/moves' — transitions must PULL players with a mystery or threat, not just move them
- LOW: Only 1 clue indicator(s) — three-clue rule requires 3 independent paths to each revelation
- LOW: Clues exist but are not labeled 'Clue A / Clue B / Clue C' — DMs cannot track which paths players have used
- LOW: Missing NPC truth sheet structure — found Wants:0 Knows:0 Hides:0. Every NPC with dialogue must have all three.

**Content gaps (LLM critique):**
- None identified
