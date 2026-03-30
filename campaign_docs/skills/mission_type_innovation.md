# Skill: Mission Type Innovation
**Keywords:** mission, type, generate, new, variety, fresh, innovation, creative, different
**Category:** learning
**Version:** 1
**Source:** seed

## Purpose
This skill teaches the self-learning system HOW to generate genuinely novel mission types that feel fresh while staying grounded in the Undercity setting. Read this before generating new mission type seeds.

---

## THE MISSION TYPE SPECTRUM

Mission types exist along several axes. Good variety means covering different points on each axis:

### Objective Axis
- **Acquisition** — get a thing (retrieval, theft, purchase, recovery)
- **Elimination** — remove a threat (assassination, creature hunt, clearing)
- **Protection** — keep something safe (escort, guard duty, defense)
- **Investigation** — find information (mystery, tracking, surveillance)
- **Delivery** — move something safely (courier, smuggling, transport)
- **Social** — change minds or relationships (negotiation, intimidation, recruitment)
- **Sabotage** — break or disrupt something (destruction, interference, delay)
- **Construction** — build or create something (establish, fortify, craft)

### Scale Axis
- **Personal** — affects one person or small group
- **Neighborhood** — affects one block or establishment
- **District** — affects a whole district
- **City** — affects the entire Undercity
- **Planar** — involves things beyond the Dome

### Urgency Axis
- **Preventive** — stop something before it happens
- **Reactive** — respond to something that just happened
- **Ongoing** — interrupt something in progress
- **Delayed** — prepare for something that will happen later
- **Cleanup** — deal with aftermath

### Moral Axis
- **Heroic** — clearly good, save innocents, stop evil
- **Gray** — morally ambiguous, both sides have points
- **Mercenary** — just business, no moral weight
- **Dark** — working for questionable employers, ethically dubious

---

## GENERATING FRESH MISSION TYPES

### The Combination Method
Pick one element from each axis and combine them:
- Acquisition + District + Reactive + Gray = "Recover evidence from a warehouse fire before the FTA seals the scene — the evidence could implicate a Warden OR prove their innocence"
- Sabotage + Personal + Preventive + Mercenary = "Destroy someone's alibi before they can use it in tomorrow's trial — no questions asked"
- Investigation + Neighborhood + Ongoing + Heroic = "Track down the source of poisoned water affecting the Warren's Collapsed Plaza while people are still getting sick"

### The Faction Lens Method
Take a generic mission type and filter it through a specific faction's perspective:
- Generic: "Retrieve a stolen item"
- Iron Fang: "Retrieve a stolen shipment before the buyer realizes it's missing — then deliver it as if nothing happened"
- Serpent Choir: "Retrieve a stolen contract scroll — the thief doesn't know it's magically bound to destroy them if they break the seal"
- Patchwork Saints: "Retrieve a stolen community fund — but the thief is a desperate parent trying to afford healing for their child"

### The Complication Method
Take a simple mission and add a specific, interesting complication:
- Simple: "Escort a merchant through the Warrens"
- + Time Pressure: "...but you have 4 hours before the Outer Wall gates close"
- + Hidden Cargo: "...who is secretly transporting a rift-touched artifact they don't know is dangerous"
- + Pursuit: "...while Obsidian Lotus assassins hunt them for a past debt"
- + Moral Dilemma: "...but the 'merchant' is actually a people smuggler helping refugees escape"

### The Inversion Method
Take a common mission type and flip its assumptions:
- Normal: "Clear monsters from a location"
- Inverted: "Protect monsters in a location from hunters who have legal rights to kill them"
- Normal: "Assassinate a target"
- Inverted: "Prevent your own assassination — someone put a contract on YOU"
- Normal: "Retrieve an artifact"
- Inverted: "Return an artifact to its dangerous resting place before its curse spreads"

---

## WHAT MAKES A MISSION TYPE SEED GOOD

A mission type seed is a 1-2 sentence description used to prompt the full mission generator. Good seeds are:

### Specific Enough to Be Evocative
**Bad:** "Do a job for the Iron Fang"
**Good:** "Intercept a Warden evidence shipment before it reaches the Grand Forum courthouse — make it look like a random robbery"

### Open Enough to Allow Variation
**Bad:** "Kill the half-orc assassin named Grukk in the Soot & Cinder at midnight"
**Good:** "Eliminate an assassin who has been targeting Guild Spires merchants — the Consortium wants it quiet"

### Grounded in Setting
**Bad:** "Defeat the dragon threatening the kingdom" (wrong setting)
**Good:** "Something is killing rift-touched creatures in the Warrens before they can be studied — find out what and stop it (or help it)"

### Implying Conflict
**Bad:** "Deliver a package"
**Good:** "Deliver a package through Obsidian Lotus territory — they want what's inside, and they know you're coming"

---

## MISSION TYPE FORMAT

When generating mission types, output them as plain text lines:
```
Infiltrate a Glass Sigil archive to alter a prophecy record before it's presented to the Tower Authority — someone's future depends on the edit
Protect a Serpent Choir contract mediator during negotiations with an angry god's avatar — the god disagrees with the terms
Track a Patchwork Saint who went missing while investigating the Collapsed Plaza — they found something they shouldn't have
```

**Format Rules:**
- One sentence or two short sentences
- No numbering (no "1.", "2.", etc.)
- No bullet points
- No faction name prefix (let the seed describe, not label)
- Include the hook/complication in the description
- Keep under 150 characters per type

---

## TYPES TO AVOID GENERATING

### Already Common (don't need more)
- Basic "clear the dungeon" missions
- Simple escort without complications
- Straightforward assassination
- Generic "investigate the disturbance"

### Setting Violations
- Anything involving Rifts (separate system handles these)
- Anything referencing surface world, other cities, or outside the Dome
- Anything involving factions not in the lore
- Anything requiring travel times longer than the Undercity allows

### Tone Violations
- Joke missions that break immersion
- Grimdark edgelord content
- Missions that require evil PC actions with no alternative
- Anything involving real-world issues anachronistically

---

## TRACKING VARIETY

The self-learning system should track:

### Mission Type Categories Seen Recently
- How many acquisition vs elimination vs investigation etc.
- Which factions have posted missions
- Which districts have been featured

### Gaps to Fill
If the last 10 missions were all combat-focused:
→ Generate social/investigation seeds next cycle

If Iron Fang has 40% of missions:
→ Generate seeds for underrepresented factions

If everything is in Markets Infinite:
→ Generate seeds featuring Outer Wall, Warrens, Sanctum Quarter

### Innovation Score
Rate each generated seed:
- Does it combine elements in a new way? (+1)
- Does it include an interesting complication? (+1)
- Does it serve an underrepresented faction? (+1)
- Does it feature an underused objective type? (+1)
- Does it have a moral dimension? (+1)

Aim for seeds scoring 3+ out of 5.

---

## OUTPUT FORMAT

When generating new mission type recommendations:

```markdown
# Skill: Mission Type Innovations — [Date]
**Keywords:** mission, type, new, variety, fresh, seeds
**Category:** learned
**Version:** 1
**Source:** self-learned

## Current Type Distribution
[Summary of what types have been common]

## Underrepresented Areas
- [Category/faction/district that needs more missions]

## New Mission Type Seeds
[5-10 new mission type descriptions, plain text, one per line]

## Reasoning
[Brief explanation of why these seeds address the gaps]
```

Keep it under 2000 characters. Focus on the seeds themselves.
