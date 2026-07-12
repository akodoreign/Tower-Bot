# Buglog
# Mission Pipeline Quality Audit — started 2026-05-18

Previous bug log archived to: buglog_archive_20260518.md

Operating note: quality and correctness matter more than speed for this bot. A slow, complete mission or image pipeline is preferable to a fast fallback that silently drops maps, prose, faction context, portraits, or rules detail.

Fixing rule: before fixing any bug in this file, first smoke test the current behavior and map the connected callers. After the fix, run the same smoke path again. Do not patch from the note alone.

---

## Active Bugs

*(None carried forward from archive — all B-1 through B-64 closed as of 2026-05-18.)*

---

## Pipeline Quality Audit — 2026-05-18

### Test mission used for all pipeline audits

```
Title:   The Iron Scar Contract
Body:    Iron Fang Consortium enforcer Vex Kraugh has been embezzling artifact
         revenue. Senior blade Mira Osei hired the party to recover ledgers
         proving his guilt from Kraugh's safehouse in the Scrapworks, without
         alerting him — alerting Kraugh would trigger a purge of the evidence.
Faction: Iron Fang Consortium
Tier:    high-stakes
Level:   5
NPCs:    Vex Kraugh (enforcer, corrupt), Mira Osei (senior blade, client)
Stakes:  Evidence purge if alerted; faction purge of party if they fail quietly
```

Pipeline findings below. Each entry records:
- Prompt structure quality
- Mission-specific context injection
- Narrative completeness
- DM usability (can a DM run this without inventing content?)
- Suggested improvements

Quality grades:
- **A** — DM can run the module cold, zero invention required
- **B** — DM needs to fill minor gaps, structure is solid
- **C** — DM must invent key content; scaffold is present but incomplete
- **D** — Significant gaps; mechanics work but narrative is placeholder-level

---

## Tier A — Fully Runnable

### assassination_pipeline.py — **A**

**What it does:** 5 sequential LLM stages — briefing, target profiling, surveillance leads, approach options, exfil. 10-retry loop with exponential backoff on every stage. Separate hardcoded fallback for each stage.

**Context injection:** Heavy. Client style is hardcoded per faction (FACTION_CLIENT_STYLES). Security tier derived from mission tier. Hit site type is faction-appropriate (hardcoded HIT_SITE_TYPES). Target routine has specific time windows, guard counts, and activity labels.

**Strengths:**
- Only pipeline with retry budget per generation stage (10 attempts each)
- Fallback plans are themselves detailed — target routine has 3 time windows with locations and guard counts; approaches have 3 complete option sets with skill DCs and key risks; exfil has 2 named escape routes
- Security label is mechanically useful (light/moderate/heavy/extreme → guard count, patrol pattern, alarm type)
- Surveillance leads include specific time windows, what is learnable, and check type
- Target conscience trigger is a moral hook baked into the stat line

**Gaps:**
- Target name is LLM-generated, not pulled from mission body. If the mission names the target explicitly, the pipeline ignores it.
- No scene-by-scene read-aloud text. DM gets briefing + approach + exfil but no moment-to-moment scene structure.
- 5-stage sequential structure means a partial LLM failure leaves the module lopsided.

**Improvements:**
1. Before generating the target, scan `mission.body` for capitalized NPC names and pre-populate the target name field. Only use LLM-generated name if mission body is bare.
2. Add a 6th stage: a brief read-aloud for the hit site itself (2-3 sentences). Currently the DM has to describe the location cold.
3. Add a `reaction_if_warned` field to target stat block — what does the target do if they know the party is coming?

---

### investigation_pipeline.py — **A**

**What it does:** Single LLM call producing a full case structure. Explicitly extracts canon terms from mission body (regex on capitalized names, faction names, location names). Injects up to 12 canon terms + 8 stakes phrases into prompt. Rejects generic output if specificity score < 3.

**Context injection:** Best in class. Canon extraction regex is broad and effective. Stakes phrases ("purge", "discovery", "will be silenced") are extracted literally from mission body.

**Strengths:**
- Generic rejection with defined markers (e.g., "rumor, fear, and faction pressure decide") prevents lazy shells
- Clue web is structured: each clue has source, what it proves, and what it unlocks
- Timeline is linear with specific actors and places
- Scene secrets list gives DM hidden information per location
- Accusation standard is explicit — DM knows exactly when the party has enough
- Long_rest_revelation adds a mid-case pivot

**Gaps:**
- Clue web is not DM-rollable. DCs are not generated per clue — DM must assign difficulty ad-hoc.
- No read-aloud text. The DM gets the case structure but no moment-to-moment narration.
- Public story vs truth tension is stated but not dramatized — there are no NPCs with contradictory testimonies pre-written.
- If mission body lacks NPC names or place names (bare missions), canon_terms will be empty and the pipeline falls through to a thin fallback.

**Improvements:**
1. Add `skill_check` + `dc` to each clue web entry (format already has `source` and `proves` — dc is the missing field).
2. Add a `witness_list` array (name, what they say publicly, what they actually know, how to get them to talk) — currently the DM must invent these.
3. Flag when `canon_terms` is fewer than 3 terms and warn the DM at the top of the module that the mission body was too bare to anchor the investigation.

---

### puzzle_pipeline.py — **A**

**What it does:** Single LLM call. Same canon extraction as investigation. Rejects generic output (GENERIC_PLAN_MARKERS). Has a hardcoded fallback oath-circuit puzzle that is itself fully playable.

**Context injection:** Same as investigation — 12 canon terms + 8 stakes injected. `exact_solution_steps` and `clue_ladder` are required output fields.

**Strengths:**
- Fallback puzzle (oath-circuit with warforged socket mechanics) is genuinely playable — DMs can run it as-is
- `answer_key` is separate from `clue_ladder` so DM never accidentally spoils the solution
- `unstick_notes` (5 entries) prevent sessions from stalling
- `wrong_attempts` (5 entries) give the DM material for failed attempts without penalizing creativity
- `world_moves` shows what happens in the game world as the party works the puzzle

**Gaps:**
- Puzzle fallback is always the same oath-circuit. If players have seen it once, the fallback is spoiled.
- No `time_pressure` field. The puzzle can be solved at leisure — there's no clock.
- `clue_ladder` entries don't specify where physically each clue lives, only what it proves.
- `alternate_solutions` list exists but doesn't specify DCs or checks for each.

**Improvements:**
1. Build 3-4 distinct fallback puzzles (not just oath-circuit) and pick one by hash of mission title, so repeat players get variety.
2. Add `time_pressure` as a required output field (e.g., "The Dome breach widens by 1 stage every 2 in-game hours").
3. Add `location` to each `clue_ladder` entry: "Found in: [specific place the party must go to retrieve this clue]."

---

### novel_pipeline.py — **A**

**What it does:** 4+ sequential agent passes — BobAgent writes prose chapters, ProAuthorReviewerAgent tightens them, BookToModuleAgent converts chapters to DM-ready scene format, DNDExpertAgent/DNDVeteranAgent produce chart pack. Generates full scene-by-scene module with read-aloud, DM notes, NPC stat blocks, and rumor/complication tables.

**Context injection:** Strongest of all pipelines. Protagonist name is injected into every pass with explicit instruction not to substitute. NPC roster, mission body, recent city news all embedded. BookToModuleAgent is instructed to pull dialogue and descriptions from the novel, not invent.

**Strengths:**
- Only pipeline producing read-aloud text for every scene
- Every NPC present in a scene has: name, race, role, dialogue sample, what they know, what they hide, what DC unlocks their secrets
- CONVERSATION BRANCHES give if-then structures for skill checks
- Chart pack includes d8 rumor table, d6 DM complication table, encounter tables, loot tables
- DM Guide includes pacing notes and difficulty adjustments

**Gaps:**
- If Pass 1 (chapter writing) fails entirely, the pipeline aborts — there is no fallback module structure to fall through to.
- Chapter word count guard (< 500 words) is a low bar. A 600-word chapter that says nothing specific would pass.
- No guard on Pass 3 (BookToModuleAgent) — if it produces a generic module shell, there's no rejection.
- The BobAgent system prompt asks for "R.A. Salvatore style" prose but this is a vague instruction; the actual novel quality depends entirely on Ollama's capabilities.
- Long runtime (can exceed 20 minutes) with no partial-save mechanism — if anything fails after chapter 4 of 5, the whole run is potentially lost.

**Improvements:**
1. Add a chapter specificity check after Pass 1: count canon term appearances. If a chapter has fewer than 3 canon terms, flag it and optionally regenerate.
2. Add a partial-save mechanism: write each chapter to disk as it completes so a pass interruption doesn't lose finished work.
3. Add a Book-to-Module generic rejection: if the produced module has fewer than 5 NPC stat blocks or fewer than 3 scenes with read-aloud, fall back to a skeleton module built directly from the chapter text.

---

### defense_pipeline.py — **A**

**What it does:** 5 LLM stages — briefing, defenses (upgrades), watch events, intel leads, waves. Defender morale pools scale from party size/level. Force modifiers validated against a lookup table and applied mechanically.

**Context injection:** Faction-appropriate defensible location via DB lookup. Attacker army type inferred from profile. Morale pools are explicit numbers, not abstract.

**Strengths:**
- Watch events are rollable (DC 14 Perception or consequence) — 8 pre-written events
- Intel leads have mechanical weight: successful lead unlocks a force modifier (−3 grunts, −4 morale)
- Wave composition gives exact grunt count, lieutenant count, commander present flag, and reinforcement timing
- Between-wave downtime is written: the DM has something to do with those 10 minutes
- Morale state thresholds (Steady/Shaken/Breaking/Routed) have mechanical penalties

**Gaps:**
- Briefing fallback is minimal: "{faction} tells party to hold {location}" — loses mission-specific stakes entirely
- Defenses upgrade fallback is 5 hardcoded generic upgrades (wall, chokepoint, etc.) — not location-specific
- No NPC names in watch events — events are fully generic ("A scout appears")
- No social/RP hooks before the battle begins — players arrive, defenses are explained, waves start

**Improvements:**
1. Inject mission NPC names into watch event descriptions — if the mission names a local militia captain, one event should be that captain doing something.
2. Add a `pre-battle_scene` field: a brief RP window (5-10 minutes in-game) where players can speak to defenders, set up one extra upgrade, or gather intel. Currently the module jumps straight to wave 1.
3. Briefing fallback should reference the attacker faction by name and the specific location — currently it drops both.

---

### recovery_pipeline.py — **B+**

**What it does:** Single LLM call producing a 28+ key recovery structure. Canon extraction active. Rival party mechanics with escalating pressure clock. 6-beat investigation trail with skill checks and fail-forwards.

**Context injection:** Faction style hardcoded per faction (FACTION_STYLE). Rival party pulled from DB player_characters if available. Recent news injected. DCs derived from tier/level.

**Strengths:**
- 6-beat trail has: clue, skill, DC, success text, fail-forward text — DM never gets stuck
- Chain of custody is a 5-beat narrative progression (who had it → who has it now)
- Dialogue bank pre-writes 16 lines across sponsor, witness, holder, rival, clerk, local, owner
- Outcome table explicitly ties contract result to pay (intact/usable/truth-only/wrong holder/destroyed)
- Rival clock escalates mechanically through 4 stages

**Gaps:**
- Only generates 0 maps currently (noted in code). The retrieval scene has no visual anchor.
- No read-aloud for the retrieval scene — DM must narrate cold
- Rival party from DB is player characters — this may produce the party seeing their own party sheet as rivals

**Improvements:**
1. Generate 1 map for the retrieval scene location (the place where the target is held).
2. Add read-aloud text to the retrieval_scene (2-3 sentences describing the space when the party first arrives).
3. Rival party should be drawn from DB NPCs or `adventurer_parties` table, not `player_characters`.

---

## Tier B — Solid Structure, Minor Gaps

### sabotage_pipeline.py — **B**

**What it does:** Single LLM call. Detector NPC pulled from DB or assigned by subtype fallback. Detection pressures pre-rolled (3-5). Faction flavor hardcoded per faction. Continuity seed from recent news/mission outcomes.

**Context injection:** Strong. Faction flavor dict covers all major factions. Detector NPC is a real DB record or assigned a plausible role (curator, engineer, dock foreman, ward tech).

**Strengths:**
- `steps` field is a concrete action sequence — DM has the sabotage procedure
- `immediate_effect`, `ripple_effect`, `catastrophic_failure` give 3 outcome tiers
- Detection pressures pre-rolled and specific to subtype
- Continuity seed ties to recent game world state

**Gaps:**
- `steps` fallback is abstract: ["Reach target", "Bypass first protection", "Apply sabotage", "Reset scene", "Escape", "Survive trigger"] — loses all mission specificity
- No skill checks on steps. The party knows what to do but not what rolls are required
- `briefing` is a single paragraph. No contact NPC dialogue, no meeting location
- `debrief` is a single sentence

**Improvements:**
1. Add `check` (skill + DC) to each step. "Bypass first protection → DC 15 Thieves' Tools or Arcana."
2. Add a `contact_intro` field (2-3 lines of contact dialogue before the briefing). Currently the module jumps straight to briefing text.
3. `debrief` should include what the sabotage achieved in the world, what the faction gained, and what the party's relationship to the faction is now.

---

### heist_pipeline.py — **B**

**What it does:** Single LLM call. Heavily pre-rolled: target, location, complications, crew assets, approach options all rolled before LLM call. Faction/location from DB.

**Context injection:** Strong. Shady sponsor, target owner, location, and district all pulled from DB. Complication seed adds unpredictability.

**Strengths:**
- 15+ output keys — the most comprehensive LLM output spec of the non-investigation pipelines
- Security plan is a 5-item ordered list of layers (not just "there are guards")
- 5 approach options give the party real choice
- `double_cross` field means the DM has a twist ready if the session needs it
- `casing_opportunities` are pre-rolled from real game options

**Gaps:**
- No generic-shell rejection. If Ollama returns thin one-liner answers per key, the module accepts them
- No read-aloud text. The DM gets security plans and approach options but no scene narration
- `heat_fallout` (3-4 items) is under-specified — heat is a core mechanic but gets less attention than the score itself

**Improvements:**
1. Add a generic rejection check: if any of the 3 key fields (briefing, score, security_plan) are under 50 characters, reject and regenerate.
2. Add a `site_entry_scene` (read-aloud for the moment the party first enters the target location).
3. `heat_fallout` should specify which faction tracks heat, at what threshold, and what the mechanical consequence is.

---

### infiltration_pipeline.py — **B**

**What it does:** Single short LLM call (5 keys). Most content is pre-rolled: 8-NPC social cast, 4 cover options, 9-scene sequence. Alert track is deterministic.

**Strengths:**
- Social cast is the richest in any pipeline: 8 NPCs with roles, attitudes, and leverage. DM can improvise interactions.
- Alert track is mechanical: 5 states with specific triggers and consequences
- Cover options include associated skills and social consequences of failure
- Scene sequence is linear — DM has a session structure

**Gaps:**
- LLM briefing (5 keys) is the weakest prompt in any pipeline (~450 chars). Objectives are abstract.
- Social cast NPCs are role-labeled but don't have stat blocks or skill modifiers
- No read-aloud text for any scene in the 9-scene sequence
- No explicit connection between social cast members and the target objective — DM must figure out which NPC is the key

**Improvements:**
1. Increase the briefing prompt to 800+ chars: inject faction culture notes, the primary objective NPC's name (if in mission body), and the social cost of failure.
2. Add one NPC in the social cast who is explicitly "the gatekeeper" — the person whose cooperation is required to reach the objective, even if the party doesn't know it.
3. Add read-aloud for scene 1 (arrival/entry) and scene 9 (exit/debrief). The middle scenes can remain DM-run.

---

### discovery_pipeline.py — **B**

**What it does:** Single LLM call, 20 output keys. Canon extraction active, generic rejection active. Same pattern as investigation/puzzle.

**Strengths:**
- `identification_steps` has skill/dc/success/failure per step — mechanically complete
- `containment_rules` prevent "we just take it home" shortcuts
- `faction_claims` introduce political conflict over what was discovered
- `implication_tree` shows downstream world consequences
- Generic rejection prevents lazy "mysterious artifact" output

**Gaps:**
- `handling_states` are mechanical but don't specify what triggers each state transition
- No NPC who specifically wants the discovery kept secret (only faction_claims which are more political than personal)
- `fate_options` (6 items) are the resolution options but lack specific skill checks or faction consequences

**Improvements:**
1. Add a `keeper_npc` field: one named NPC (from mission canon if available) whose personal goal conflicts with the party's choices about what to do with the discovery.
2. Add `check` + `consequence` to each `fate_option`.
3. `first_imagery` (8 items) is a prompt list for A1111 but is never presented to players as read-aloud. Convert the first 3 items into a `opening_read_aloud` field.

---

### strange_occurrences_pipeline.py — **B**

**What it does:** Single LLM call, 22 output keys (most in class). Canon extraction active, generic rejection active. Evidence ladder has 7 entries with skill/dc/clue/fail.

**Strengths:**
- Witness structure (name, what they say, what they hide, what DC unlocks) is strong
- Resolution paths specify choice, result, pay, kharma, and faction reaction — complete outcome table
- Coroner records add the world-building layer that makes strange occurrences feel real
- `contradictions` (6 items) give DM material when players press details
- TNN angle ties to the news bulletin system

**Gaps:**
- No read-aloud for `first_scene`. DM gets a description but it's prose, not narrated.
- `combat_or_hazard_options` (5 items) are under-specified — they list options but not stat blocks or mechanical triggers
- `occurrence_behavior` is a single sentence. The actual in-session behavior of the phenomenon is underspecified.

**Improvements:**
1. Add `opening_read_aloud` (3 sentences, past tense, sensory). Currently the DM must convert the first_scene description on the fly.
2. Give each `combat_or_hazard_option` a CR and a trigger condition ("if players attack the phenomenon directly → CR 5 construct with these stats").
3. Expand `occurrence_behavior` to include: what it does on its turn, what makes it stop, what triggers escalation.

---

### rescue_pipeline.py — **B**

**What it does:** Single LLM call, 15 keys. Canon extraction active, generic rejection active. Rescue clock is a 4-beat escalation tied to in-game time.

**Strengths:**
- Clock escalation is explicit: 4 beats with specific consequences at each
- Extraction standard tells DM exactly what "success" looks like
- `survivor_quote`/`family_quote`/`official_quote` give emotional texture to the outcome
- TNN/reporter mechanic is baked in

**Gaps:**
- Scene list is abstract: ["approach", "locate", "clear obstacle", "stabilize", "extract"] — no read-aloud, no specific obstacles
- Captor_or_pressure is named but has no stat block
- Target_state affects roleplay significantly but has no mechanical consequence
- No map is generated except for "active rescue" subtypes

**Improvements:**
1. Each scene needs 1-2 lines of read-aloud and one skill check with DC.
2. `captor_or_pressure` should include a CR and 2-3 special abilities relevant to the rescue context.
3. The target's `target_state` (injured, brainwashed, willing prisoner, etc.) should carry a mechanical consequence during extraction (e.g., injured target: party must succeed DC 12 Medicine or target loses 1d6 HP during extraction).

---

## Tier C — Present But Incomplete

### ambush_pipeline.py — **C+**

**What it does:** 2 LLM calls (target details, briefing). Pre-rolled trap menu (10 traps), heat tracker (4 states), guard roster from DB or generated. Only 1 Ollama attempt per call (no retry).

**Strengths:**
- Trap menu is the richest single pre-rolled table in any pipeline: 10 named traps with setup DC and mechanical effect
- Guard roster is faction-specific with documented behavior (e.g., Obsidian Lotus guards watch obvious spots as bait)
- Heat tracker specifies triggers for each state and faction-specific consequences
- Map plan has 4 approach routes — DM keeps actual route secret until target appears

**Gaps:**
- Only 1 Ollama attempt per generation step. Any failure silently falls to fallback.
- No read-aloud for the ambush moment itself
- Guard roster has names and roles but no stat blocks or skill modifiers
- `target durability` (AC/HP) is generated for items/convoys but persons only get "behavior" — no mechanical stats
- Bonus objectives exist but their mechanical reward is not specified

**Improvements:**
1. Add at least 3 retry attempts per Ollama call — single attempt is the lowest retry count of all pipelines and risks silent degradation.
2. Add `stat_block` to person targets: AC, HP, and one special behavior when cornered (surrender, flee, fight).
3. Add read-aloud for the "target spotted" moment: the sentence the DM reads when the target or convoy enters the ambush zone.

---

### battle_pipeline.py — **C+**

**What it does:** 4+ LLM calls (briefing, pocket fights × N, support actions, debrief). Conflict type detection. Void creature selection. Party-scaling. 10 Ollama retries.

**Context injection:** NPC contact from DB. Location faction-appropriate. Opposing faction/void creatures scaled to party level.

**Strengths:**
- Pocket fights are individually structured (name, setting, enemy, tactic, hazard, outcome win/loss)
- Glory fight is an optional high-stakes encounter that scales reward
- Support table has 5 actions — non-combat party members can contribute
- Morale tracker anchors the overall battle

**Gaps:**
- Briefing prompt is only ~500 chars. The contact speech is 2-3 sentences. There is no "why does this battle matter to the city/faction" text for the DM.
- Pocket fight descriptions are short — typically 1-2 sentences each
- No read-aloud for any scene. DM narrates the entire battle cold.
- Support actions are generic (call for backup, heal, scout, etc.) — not faction-specific
- No consequence if the party abandons the battle mid-way

**Improvements:**
1. Expand the briefing prompt to 1000+ chars — add faction stakes (what does the hiring faction lose if this battle fails?), a named officer on each side, and a specific location detail.
2. Each pocket fight needs 1-2 sentences of read-aloud ("As you crest the barricade, you see—").
3. Add a `desertion_consequence` field: what happens narratively and mechanically if the party retreats from a pocket fight.

---

### assault_pipeline.py — **C+**

**What it does:** 2 LLM calls (briefing, chokepoints). Commander archetype mapped per defending faction. Morale pools scaled. 10 Ollama retries.

**Strengths:**
- Chokepoints include party solution (skill check suggestion) — best tactical detail in class
- Commander archetype has abilities + surrender thresholds + instakill prevention
- Morale track with numeric pools
- Home advantage mechanics spelled out per defender type
- Trickle mechanics documented (grunts arrive as waves, not all at once)

**Gaps:**
- Briefing prompt is short (~600 chars). `objective_desc` is 1 sentence.
- 3 win conditions are hardcoded strings ("Hold the line", "Break morale", "Neutralize commander") — not mission-specific
- No read-aloud for the opening scene (the party sees the position for the first time)
- Chokepoint descriptions are 1-2 sentences; no read-aloud for when the party enters each one

**Improvements:**
1. Win conditions should be generated by the LLM from mission context, not hardcoded. What does "winning" specifically look like for this faction in this assault?
2. Add `position_approach_read_aloud`: 3 sentences narrating the moment the party first sees the target position.
3. Add `commander_dialogue`: 2-3 lines the commander says at key moments (when the fight starts, when morale breaks, when cornered).

---

### infestation_pipeline.py — **C**

**What it does:** 3 LLM calls (monster roster, room batches × N, fallback room pass). ASCII layout deterministic. Per-room: read-aloud, dm_notes, monsters, features, exits, treasure, hazard. 10 retries on room content.

**Strengths:**
- ASCII layout is deterministic and printed in module
- Monster roster has actual stats (HP, AC, attacks, special traits)
- Room content stub detection (retries rooms that return placeholder text)
- Fallback room content is subtype-specific (sewer vs dungeon vs ruins features differ)
- Batch prompting (4 rooms at a time) makes generation efficient

**Gaps:**
- Monster types are chosen from a limited pool and not connected to mission plot hooks. A sewer infestation will always have rats and oozes regardless of mission.
- Room content does not reference mission-specific NPCs or stakes. Each room is self-contained.
- No boss encounter room structure beyond "boss creature is here" — no read-aloud, no special triggers
- No plot hook in any room: there's no "this room contains evidence connecting to Vex Kraugh" or equivalent

**Improvements:**
1. Add a `plot_room` to each layout: one room that contains a mission-specific discovery (ledger, body, evidence). Content of this room is generated with the mission body as context.
2. Boss room needs its own LLM pass: read-aloud entrance, boss behavior, phase triggers, and what happens when it dies (does the infestation collapse? does something worse emerge?).
3. Extract any named location from the mission body and use it as the room that the infestation is centered around (e.g., "Kraugh's safehouse basement" as the starting room, not a generic sewer entrance).

---

### exploration_pipeline.py — **C**

**What it does:** Single LLM call, 16 keys. Canon extraction and generic rejection active. 3 pre-structured scenes (Survey, Complication, Extraction) with mechanics.

**Strengths:**
- Route log has 6 points each with read-aloud, DM notes, skill check, DC, and failure consequence
- Scenes have trigger, read-aloud, DM notes, mechanics, and outcome — complete scene structure
- Deliverables list specifies what the party brings back and what it proves
- Endpoint revelation requires a specific truth (what is actually at the end?)

**Gaps:**
- Route log read-aloud entries are template-style (1 sentence). Not vivid.
- Survey scene and Complication scene are structurally the same — no differentiation of tone
- `hazards` (5 items) are listed but have no stat blocks or skill checks attached
- No NPC in the exploration — the party is entirely alone

**Improvements:**
1. Route log read-aloud should be 2-3 sentences, sensory, present-tense.
2. Hazards need a DC and a consequence: "Unstable floor: DC 13 Athletics or fall 20 ft (2d6 bludgeoning)."
3. Add an optional `encounter_npc`: one NPC the party meets during the exploration who is also present for a different reason (rival, refugee, creature with a name). The isolation of exploration modules is their main weakness.

---

### first_contact_pipeline.py — **C**

**What it does:** Single LLM call, 16 keys. Canon extraction and generic rejection active. Tower primer is hardcoded (8 concepts). Translation tracker and panic meter are mechanical trackers.

**Strengths:**
- Translation tracker (5 stages) gives progress mechanic to communication
- Panic meter escalates if players make poor choices
- Taboos list prevents the DM from winging interpersonal conflict incorrectly
- Tower primer gives the DM 8 "facts about the Undercity" to use as dialogue props

**Gaps:**
- Tower primer is always the same 8 items regardless of what the contact needs to understand. A dimension-displaced noble needs different context than a shipwrecked sailor.
- `contact_protocol` steps are LLM-generated but fallback is generic — "step 1: approach slowly"
- No stat block for contact in case communication breaks down entirely
- No consequence for using the wrong approach beyond "panic meter rises"

**Improvements:**
1. Make 2-3 of the Tower primer items mission-specific. What specific aspect of the Undercity is most relevant to this particular contact's origin?
2. Add `contact_defense` stat block: only triggered if panic meter maxes out, but the DM needs it ready.
3. Add `translation_reward`: what specific information becomes available at each translation stage. Currently the DM must invent what "speaking more clearly" unlocks.

---

## Tier D — Mechanics Work, Narrative Weak

### negotiation_pipeline.py — **D+**

**What it does:** Single LLM call, 15 keys. Faction name canonicalization. Marker system (-10 to +10 scale). 20-line dialogue bank. 6 outside favor options. 8 research lanes.

**Context injection:** Weakest of the mission-specific pipelines. Only faction names are pulled from mission context. Mission body is not injected into the dialogue bank or research lanes.

**Strengths:**
- Marker system is elegant: research and favors shift the marker, success/failure are defined by range
- DC math is correct: tier + party level produces realistic DCs
- Outside favors introduce non-party leverage (faction elder, TNN broadcast, divine witness)
- Research lanes have specific skills and DCs

**Gaps:**
- **No generic rejection.** Any LLM output is accepted. The pipeline has no specificity guard.
- Dialogue bank (20 lines) is faction-generic — the same lines would work for any negotiation between any two factions
- `side_a_wants` / `side_b_wants` are LLM-generated but fallback is boilerplate ("Wants a fair deal")
- Red lines are not specified mechanically — "crosses a red line" is undefined as an action
- No read-aloud. DM must do all the scene narration.

**Improvements:**
1. Add generic rejection using the same canon terms + specificity scoring as investigation/puzzle. Reject dialogue banks that don't mention faction-specific goals.
2. Inject mission body (first 500 chars) into the dialogue prompt. The dialogue should reference the actual dispute, not a template dispute.
3. Red lines need mechanical definition: "If Side A hears [specific topic], marker immediately moves to −5 and they stand and leave." Currently the DM must interpret "red line" ad-hoc.
4. Add a `scene_anchor`: 2-3 sentences setting the physical space (where are they meeting, who else is in the room, what's the ambient tension). Currently there is no read-aloud entry point.

---

### escort_pipeline.py — **D+**

**What it does:** Single LLM call (briefing only). Target randomly selected from archetypes. Pickup/delivery locations randomly selected. Route maps generated (clean + DM version). Vetting check, trap menu, ambush mechanics pre-rolled.

**Context injection:** Minimal. Mission title and body used as flavor only. Target is NOT read from mission body. If the mission names a specific person or item to escort, the pipeline ignores it.

**Strengths:**
- Vetting mechanics are interesting (faction-keyed: some factions require combat proof, others require social proof)
- Trap menu is present
- Two maps (clean route + DM ambush version) give the DM visual support
- Outcome table specifies consequences for 4 delivery states (safe, injured, item damaged, escort failed)

**Gaps:**
- **Fundamental design gap**: target is always random. An escort mission for "Mira Osei" will generate a random target, not Mira Osei.
- Pickup and delivery are always random locations, not the locations named in the mission
- `contact_speech` fallback is 1 sentence — the shortest briefing in all pipelines
- No NPC personality for the escort target — the DM has no idea how to roleplay them
- Ambush position is randomized; no tactical notes for how the ambush plays out

**Improvements:**
1. **Critical fix**: Scan mission body for NPC names (same regex as investigation/puzzle) and use the first person-name hit as the escort target. Only use random archetype if no name found.
2. Similarly extract location names from mission body for pickup/delivery. Random fallback only if not found.
3. Add `target_personality` field (2-3 traits + one thing they'll do under stress) and `target_request` (one thing the target asks of the party during the escort that creates roleplay friction).
4. Add briefing prompt context: inject mission body (first 400 chars) and faction background into the prompt, not just the title.

---

### gather_pipeline.py — **D**

**What it does:** 3 LLM calls (contact scene, location description, debrief lines). Item details are non-LLM (faction profile lookup + DC math). Encounter table is pre-written (20 comedic, 13 inconvenient, 11 combat items). 

**Context injection:** Faction and item category from faction profile. Mission body used for flavor only in contact prompt. No NPC name injection.

**Strengths:**
- DC math is faction-appropriate and scales to party strength — the mechanical spine is solid
- Quota system is well-designed (stock > quota = success)
- Encounter table (44 entries) is the most extensive random table in any pipeline
- Fragility mechanic adds texture (some items need Stealth to gather, others need raw Strength)

**Gaps:**
- **Contact scene LLM prompt is the shortest in all pipelines** (~600 chars). It produces 5 keys, one of which is the gather location — which is the only location reference.
- Contact NPC has no personality beyond 3 negotiation beats. There is no reason to interact with them beyond the mission handoff.
- Mission body is flavor-only in the prompt. If the mission explains *why* a specific item is needed (lore, urgency, faction politics), the contact scene never reflects it.
- Debrief is only 2-3 lines. There is no "what happened in the world because we gathered this" payoff.
- Encounter table entries are good but unlabeled by zone — a sewer gather and a Neon Row gather pull from the same table.

**Improvements:**
1. Inject mission body (first 500 chars) into contact scene prompt. The contact should reference why *this specific item* matters right now.
2. Divide encounter table by location type (underground, market, wilderness, residential) so encounters fit the setting.
3. Add `world_consequence` field to debrief: 1-2 sentences describing what changed in the city because the party completed this gather. Currently gather missions feel consequence-free.
4. Add `contact_motivation` (1-2 sentences): why does this contact specifically need the party for this, and what do they gain? DMs need this to roleplay the contact believably.

---

## Cross-Pipeline Findings

### Issue 1 — Missing read-aloud across most pipelines

Investigation, puzzle, novel, and strange occurrences produce prose the DM can use. Most combat-oriented pipelines (battle, assault, ambush, infestation, heist, escort) provide zero read-aloud text. DMs must narrate every scene cold.

**Recommendation:** Every pipeline should produce at minimum: an `opening_read_aloud` (3 sentences, when the party first arrives), and an `action_read_aloud` (2 sentences for the moment the core conflict begins). These are short enough that even a weak LLM can produce them, and they dramatically raise DM usability.

---

### Issue 2 — Canon extraction not universal

Six pipelines (escort, gather, ambush, infestation, battle partially, negotiation) do not extract canon terms (NPC names, locations, stakes) from the mission body. The same regex infrastructure used by investigation/puzzle/rescue/recovery should be standardized across all pipelines as a shared `_mission_context()` call.

**Recommendation:** Standardize `_mission_context()` as an import from a shared module (not copy-pasted per pipeline). All 22 pipelines should call it and inject the result into their primary LLM prompt.

---

### Issue 3 — Generic rejection not universal

Seven pipelines have no specificity guard at all (escort, gather, negotiation, ambush, infestation, battle, assault). Five have it (investigation, puzzle, discovery, strange_occurrences, rescue/recovery). 

The absence of rejection means a lazy LLM response (e.g., "The party must deal with a threat to the faction") passes through as a complete module.

**Recommendation:** At minimum, add a character-count check on the primary LLM output's briefing field. If briefing < 150 characters, reject and regenerate. This is a low-cost guard that catches the most egregious empty outputs.

---

### Issue 4 — Fallback quality is uneven

Assassination and puzzle fallbacks are genuinely playable. Escort, gather, and negotiation fallbacks are 1-2 sentence placeholders.

**Recommendation:** Every fallback should produce a module where the DM has: a briefing (5+ sentences), a scene list (at minimum 3 entries), and a resolution condition. The fallback does not need to be creative — it needs to be functional.

---

### Issue 5 — Escort has a fundamental design flaw

Escort randomly selects targets and locations, ignoring mission body content entirely. This makes escort missions disconnected from the campaign setting in a way no other pipeline suffers.

**Recommendation:** This is a code change — scan mission body for NPC name and location before reaching for random selection. Fix is in `_resolve_roles()` or equivalent.

---

## Priority Fix Order

| Priority | Pipeline | Issue | Effort | Status |
|----------|----------|-------|--------|--------|
| 1 | escort_pipeline | Canon injection missing entirely (fundamental) | Med | [FIXED — Claude 2026-05-18] |
| 2 | negotiation_pipeline | No generic rejection; dialogue ignores mission body | Low | [FIXED — Claude 2026-05-18] |
| 3 | gather_pipeline | Prompt too short; no world consequence | Low | [FIXED — Claude 2026-05-18] |
| 4 | battle_pipeline | Briefing too short; no read-aloud; no abandonment consequence | Med | [FIXED — Claude 2026-05-18] |
| 5 | assault_pipeline | Win conditions hardcoded; no position read-aloud | Low | [FIXED — Claude 2026-05-18] |
| 6 | All (22) | Canon extraction pattern — each pipeline keeps its own copy (intentional) | Med | [CLOSED — each pipeline is intentionally distinct; no shared module. Canonical pattern is investigation_pipeline.py:_mission_context(). New pipelines should copy that pattern locally.] |
| 7 | heist/infiltration/defense/escort/ambush | Opening read-aloud added to 5 highest-impact pipelines | High | [FIXED — Claude 2026-05-18] |
| 8 | investigation | Add DC to clue_web entries | Low | [DONE - Codex 2026-05-18: fallback clue_web entries now include skill/DC; LLM clue_web entries are normalized with missing skill/DC; rendered Core Clue Web prints "Check: Skill DC N"; tested with tests/test_investigation_pipeline.py] |
| 9 | puzzle | Multiple fallback puzzle templates (not just oath-circuit) | Med | [DONE - Codex 2026-05-18: puzzle fallback now varies by type (art mural, language cipher, physical mechanism, divine witness trial, rift memory loop, logic/rule grid, arcane oath-circuit fallback); before/after smoke confirmed non-arcane types no longer all become Oath-Circuit; tested with tests/test_partial_plan_normalization.py -k puzzle and py_compile] |
| 10 | novel | Partial-save mechanism between chapter passes | Med | [CLOSED — novel pipeline deprecated; replaced by individual mission pipelines which are faster and produce better results] |

## Round 2 Quality Fixes — 2026-05-18

| # | Pipeline | Issue | Status |
|---|----------|-------|--------|
| R1 | ambush | 1 Ollama retry → 3 per call | [DONE — Claude 2026-05-18: `_ollama()` now loops up to 3 attempts; cop check runs before each retry] |
| R2 | puzzle | Add time_pressure field; add location to clue_ladder entries | [DONE — Claude 2026-05-18: `time_pressure` added to LLM prompt spec and all fallback templates; all clue_ladder entries now have `where` field; renderer renders it in Clue Ladder table] |
| R3 | investigation | Add witness_list; flag bare missions | [DONE — Claude 2026-05-18: `witness_list` added to `_fallback_plan()` and LLM prompt spec; Witnesses card added to `render_investigation_module()`; DM WARNING banner shown when canon_terms < 3] |
| R4 | assassination | Pull target name from mission body; add hit site read-aloud | [DONE — Claude 2026-05-18: `_extract_target_name()` added; hint passed to `_generate_target()`; `hit_site_read_aloud` in spec, fallback, and rendered before Surveillance Leads] |
| R5 | discovery | Add opening_read_aloud | [DONE — Claude 2026-05-18: `opening_read_aloud` in LLM prompt spec, fallback, and rendered as "Read Aloud — First Encounter" card] |
| R6 | first_contact | Add opening_read_aloud | [DONE — Claude 2026-05-18: `opening_read_aloud` in LLM prompt spec, fallback, and rendered as "Read Aloud — First Sight" card] |
| R7 | recovery | Add retrieval scene read-aloud | [DONE — Claude 2026-05-18: `read_aloud` added to `retrieval_scene` spec, fallback, and rendered as italic block in `_retrieval_html()`] |
| R8 | rescue | Per-scene skill checks; captor stat block | [DONE — Claude 2026-05-18: `scene_skill_checks` and `captor_stat_block` added to prompt spec, both fallback branches, and rendered as new cards; aftermath mode suppresses captor stat block] |
| R9 | infestation | plot_room tied to mission canon; boss room dedicated pass | [DONE — Claude 2026-05-18: `_mission_context()`, `_pick_plot_room_id()`, `_generate_plot_room_content()`, `_generate_boss_enhancement()` added; both passes run after `generate_all_rooms()`; plot_anchor badge and boss enhancement section rendered in room cards] |

---

## Monster DB / DDB Import Notes - 2026-05-18

- [DONE - Codex 2026-05-18] `scripts/enrich_creatures_ddb.py` now runs DB monster import/enrichment by default for `undercity`, `undercity_high_cr`, and `faction_generic`. Legacy module creature/NPC staging-log passes are opt-in with `--include-legacy`. Chunk controls: `--dry-run`, `--monster-limit`, `--monster-sources`, `--cr-min`, `--cr-max`, `--void-only`, and `--regular-only`.
- [DONE - Codex 2026-05-18] DB-to-DDB enrichment now decodes `monsters.saves_json` so save bonuses can reach DDB instead of being dropped.
- [DONE - Codex 2026-05-18] Added and seeded `scripts/seed_faction_monster_db.py`: 18 generic faction humanoid roles for mission encounters.
- [DONE - Codex 2026-05-18] Mission critter/fodder selection now uses DB-backed rosters in infestation, battle, defense, assault, ambush fallback guards, rescue fallback captor, dungeon delve rooms, and published fallback stat blocks. Shared CR rule is party average +4 at difficulty 5, then -1/+1 CR per difficulty step.
- [DONE - Claude 2026-05-18] Fixed `_db_edit_url()` in `enrich_creatures_ddb.py` — was wrongly transforming `/monsters/ID/edit` to `/edit-monster/ID/edit` (404). Now a no-op since `push_monster_http()` already returns the edit URL. All 316 DB rows had `ddb_edit_url` corrected via `UPDATE monsters SET ddb_edit_url = ddb_url WHERE ddb_url IS NOT NULL`.
- [DONE - Claude 2026-05-18] Fixed `_CR_OPTIONS` in `src/ddb_homebrew.py` — DDB's form skips option value 28 between CR 23 and CR 24. Old mapping: CR 24→option 28 (invalid). New: CR 1-23→option CR+4, CR 24-30→option CR+5. This caused all 15 CR 24 + 1 CR 25 monsters to fail with a form validation 200.
- [DONE - Claude 2026-05-18] Fixed Sewer Hydra `languages="-"` — DDB's `languages-note` field requires either empty OR ≥2 characters (data-validation-length="2..512"). Single dash failed. Fixed in `seed_high_cr_monster_db.py` (Hydra archetype) and DB UPDATE. This caused all 16 Sewer Hydra variants (CR 8-25) to fail import.
- [DONE - Claude 2026-05-18] Improved error extraction in `push_monster_http()` — regex now strips nested HTML from error containers to expose actual DDB validation messages (e.g., "Must be within 2 and 512 characters long.") instead of returning whitespace-only strings.
- [DONE - Claude 2026-05-18] Re-ran PASS 3 import for 32 previously failing monsters: 32/32 OK. PASS 4 enrichment: 270/270 stat blocks enriched, 0 failed. Portraits not generated (A1111 lost connection mid-run). Re-run `python scripts/enrich_creatures_ddb.py --monster-sources undercity_high_cr` after A1111 is confirmed up to backfill portraits — PASS 4 will skip already-enriched rows (enriched_at set) so portrait-only backfill needs a separate mechanism or reset enriched_at for portrait-missing rows.

## Mission Generation Stability - 2026-05-19

- [DONE - Codex 2026-05-19] Investigated today's "module generation broken" reports. Logs show module jobs started but then Discord heartbeats were blocked inside `vtt_renderer.save_vtt_battlemap() -> stylize_pretty_battlemap() -> wait_for_a1111_idle()`, especially escort map generation. Root cause: synchronous A1111 pretty-map polling/sleeps were running on the Discord async event loop.
- [DONE - Codex 2026-05-19] Added `stylize_pretty_battlemap_safe()` in `src/mission_builder/vtt_renderer.py`. Tactical VTT maps are still written immediately; if called from an active asyncio event loop, the optional pretty-map pass is queued on a single background worker instead of blocking Discord.
- [DONE - Codex 2026-05-19] Updated infestation cached-map pretty pass to use the async-safe helper too. Verified all mission pipeline modules import, all `*_pipeline.py` files compile, and an async smoke test confirms `save_vtt_battlemap()` returns quickly while the pretty pass runs in the background.

## DDB Monster Ability Repair - 2026-05-19

- [DONE - Codex 2026-05-19] Added PASS 3.5 to `scripts/enrich_creatures_ddb.py`. It scans imported DB monsters with DDB edit URLs, reads the actual DDB edit form, detects monsters whose traits/actions/bonus/reactions/legendary/mythic/lair fields are all empty, and re-posts the DB stat-block ability text without generating portraits.
- [DONE - Codex 2026-05-19] Added `--repair-abilities-only` for running just PASS 3.5. Dry-run smoke with `--monster-limit 5` confirmed it can read DDB edit pages and correctly skips monsters that already have ability/action text.
