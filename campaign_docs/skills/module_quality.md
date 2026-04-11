# Skill: Mission Module Quality Standards
**Keywords:** module, mission, one-shot, adventure, generate, document, docx, scene, encounter, stat block, NPC, boss, combat, investigation, session, DM, play, run, write
**Category:** style
**Version:** 1
**Source:** seed

## Purpose
This skill governs how the bot generates D&D 5e 2024 mission module documents. It fixes systematic quality issues identified in early generated modules and establishes standards based on official WotC one-shot structure and community best practices.

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

```
### Scene [N]: [Name]

📖 READ ALOUD:
[3-4 atmospheric sentences. Sensory details: sight, sound, smell. End with something that invites player action.]

📝 DM NOTES:
- What's really going on in this scene
- What information is available here
- How this connects to the next scene

👤 NPCs PRESENT:
- [Name] — [1-line description + what they want]

🎲 MECHANICS:
- [Skill] DC [X]: [What it reveals]
- [Skill] DC [X]: [What it reveals]
- Combat: [Brief enemy summary with stat block reference]

⚡ WHAT HAPPENS:
[2-3 bullet points describing the flow of the scene — what triggers what]

➡️ TRANSITION:
[1 sentence explaining what leads to the next scene]
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
