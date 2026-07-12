---
name: module-quality
description: "Quality patterns for D&D mission modules. Use when generating mission module content via ProAuthorAgent, DNDExpertAgent, DNDVeteranAgent, or mission_compiler.py. Contains concrete patterns, good/bad examples, and anti-patterns to enforce professional module quality."
---

# Module Quality Patterns

## The Three Layers of Every Good Mission

Layer 1 — **What players are told:** The surface job. Simple, specific, actionable.  
Layer 2 — **What's actually happening:** The DM truth. The real situation behind the posting.  
Layer 3 — **What changes because of this:** The consequences that thread into future events.

A mission that only has Layer 1 is a placeholder. Layer 2 is where the story lives.

---

## Required Section Structures

### Overview (DM-facing)

Three things in one paragraph:
1. What the surface problem is (one sentence, specific)
2. What is actually happening (one sentence, specific, different from the surface)
3. What the hidden stakes are (one sentence)

```
❌ BAD:
This mission involves investigating something bad in a warehouse. Players 
will find clues and fight enemies.

✅ GOOD (from real mission):
Someone inside the Consortium's Cobbleway counting house has been skimming —
badly. Guildmaster Dhal discovered three ledgers with three different totals 
and wants outside investigators because he can't trust his own people. What 
they uncover goes deeper than embezzlement: the missing funds trace to weapons 
shipments destined for the Warrens.
```

### Background (DM-only truth)

What's really going on — written for the DM's eyes only. 4-6 sentences covering:
- The person actually responsible (with their specific motivation)
- Why the surface problem looks like what it looks like
- What the NPC contact is NOT telling the party (and why)

```
✅ GOOD (from real mission — Tithe Ledger):
Sevas was not a courier. She was a mid-tier Choir financial officer — technically 
a broker, practically a keeper of secrets. She disappeared voluntarily. She found 
records showing that Brother Enn controls a fund built from skimmed divine favour 
transactions. She took the ledger as insurance. She has not gone to anyone yet 
because she does not know who to trust. She is hiding in the Floating Bazaar, 
trying to decide what to do.
```

Note: Sevas has a *specific reason* (found incriminating records accidentally), a *specific fear* (doesn't know who to trust), and a *specific goal* (wants the ledger to reach someone who can use it). Not "she's a villain" or "she went rogue."

### Hook (future seeds)

One specific detail the party learns or encounters that will matter in a later mission. They may not know it's significant. Write it as a DM instruction.

```
✅ GOOD examples:
HOOK: The disc's partial Rift map matches a grid Dova has been assembling for two months.
She does not know the party has seen it — but when she finds out, she will ask to interview them.

HOOK: If the ledger reaches Magister Liora, she opens a Tower Authority investigation.
This takes months. It surfaces during a future posting period at the worst moment for the Choir.

HOOK: The crystal's resonance matches a frequency Dova has only seen preceding floor destabilisations.
She does not tell the party yet. This connects to three other missions this period.
```

### DM Note (tone + mechanics + recurring flag)

One sentence each:
- What this mission is about emotionally (not mechanically)
- Combat risk level
- Recurring NPC flag if applicable
- Cross-mission flag if applicable

```
✅ GOOD:
DM NOTE: Pure social mission. No combat. Wex is a recurring face if treated well —
a courier with Warrens connections who owes the party a mild favour.

DM NOTE: This is the most ethically complex mission on this board. Do not push 
the party toward any outcome — let them make the call. Brother Enn is the same 
deacon from the Lotus delivery hook.

DM NOTE: Low-stakes, flavour-rich mission that rewards careful roleplay. The crystals 
are a setup — the unusual Rift signature will resurface in a later posting or Rift event.
```

---

## NPC Depth Standard

Every named NPC in a module must have:
- **A specific reason for their current behaviour** (not "evil", not "chaotic" — a concrete human motivation)
- **Something they want from this interaction**
- **Something they will NOT reveal unless the right approach is used**
- **How they respond to the right approach** (specific, not "they cooperate")

```
❌ BAD:
Wex is a thief. He stole the relic and is hiding it.

✅ GOOD (real mission):
Wex is not a thief. He opened the package, recognised what he was carrying was 
worth more than his delivery fee, got frightened by that realisation, and has 
been paralysed by indecision for a week. He still has the disc. He wants someone 
to take the decision off him. He responds to practical assurances — not vague 
promises, specific ones. Offer him 10 EC of your own coin as a gesture of good 
faith and he hands it over immediately and buys you a drink.
```

The key: Wex's motivation is *fear and shame*, not greed. That's why intimidation half-works (he capitulates) but doesn't fully work (he may omit things). Only genuine reassurance unlocks everything.

---

## Sympathetic Villain Standard

The best villains are doing something understandable for reasons that are human and specific. Not "they're corrupted." Not "they hunger for power." A specific wound, a specific goal, a specific method.

```
✅ GOOD (from community module — Respect Your Elderly):
Neses is not a monster. She was a priestess. Her daughter was killed when the city council 
declared her goddess a false religion and sent soldiers to dismantle the temple. She survived. 
Her daughter did not. She has spent decades in an underground chamber preparing a single ritual 
to bring Ada back. The crops are dying because she needs life force. She knows this. She 
considers it a fair trade — the city that killed her daughter can starve.

❌ Why this is not just "evil":
The city council's letter is found in the bedroom: they gave two warnings, threatened death 
by hanging for heresy, then sent soldiers. Two dolls on the bedroom floor — bear and warrior. 
A child's toys. One normal pillow, one child-sized, on the bed. The villain's room tells 
her story before she speaks.
```

**The Sympathetic Villain Template:**
1. **Specific injury** — what was done to them, by whom, when
2. **Specific goal** — what they want and why it requires what they're doing
3. **Physical evidence trail** — room details, documents, objects that let players piece it together
4. **The cost** — what innocent parties pay for their grievance

When players find the letter from the city council threatening death, they understand Neses even if they have to stop her. That is the point.

---

## The Reveal Scene

When a trusted NPC is revealed as the real threat, the reveal must be **earned**. Trust has to be real first.

Structure of a working reveal:

```
1. The NPC is genuinely helpful in a way that costs them something.
   (Okawa's dretches fight the party. She arrives frightened. She pays them for the mission.)

2. The clues exist but are deniable.
   (Kitchen has vials and incense — she says it's for protection spells. Defensible explanation.)
   (DC 18 Insight detects she's not telling the whole story — players feel uncertain, not certain.)

3. The reveal reframes everything.
   ("Few would think their saviour in such a place is also their damnation.")
   The party did the villain's work for them. That is worse than being defeated.

4. The villain explains what they really wanted — and it makes sense.
   Not "I was evil all along." A specific plan with a specific logic.
```

**Rule: A reveal only hits if the audience trusted the person first.**
Write the NPC so that a first-time reader would believe them. If the deception is obvious, the reveal is flat. The DM note should flag that players who detect the lie early need to be handled carefully — the adventure doesn't break, but the DM should know what to do.

---

## Environmental Storytelling

Physical details tell NPC backstory without exposition. Every key NPC should leave traces in their environment that speak before they do.

```
✅ From community module:
The bedroom hasn't been entered in decades. On the desk: an opened letter and an open book.
Two dolls on the carpet — a bear and a woman warrior. One normal pillow on the bed, one child-sized.
No exposition needed. The DM reads this and knows everything. The players piece it together.

✅ From real mission (Wex):
He refills your drink before it's half empty. He hasn't met your eyes since you sat down.
No narration needed. The behaviour is the tell.

✅ Structure:
Room or space → 2-3 specific objects → each object implies a past event or current state
  Bad example: "The room shows signs of someone who has been living here a long time."
  Good example: "A bedroll in the corner. Three empty bottles lined up against the wall. 
                 A knife driven into the table — not stuck in anger, just stuck, like someone 
                 needed their hands free."
```

**The rule:** Each physical detail should answer one question about the NPC or raise one question the players will want answered. Not decoration. Information.

---

## Resolution Design

### The Non-Combat Path Must Always Exist

Every mission must have at least one resolution that requires no combat. The non-combat path should be described first in the module. It is not the "clever" option — it is a fully valid primary option.

```
✅ STRUCTURE:
Primary resolution (social/investigative):
  [NPC] responds to [specific approach]. [What happens specifically.]
  
Alternative resolution (if primary fails):
  [What changes the calculus. What second approach unlocks.]

Force path (if players insist):
  [What happens mechanically. What is lost or complicated by this choice.]
  [Combat-as-last-resort always has a cost.]
```

### The Moral Choice (at least one per posting period)

At least one mission per posting period should have no clean outcome. Not "succeed or fail" — but "which outcome do you choose, and what do you give up?"

```
✅ REAL EXAMPLE:
The Choice:
- Return the ledger to the Choir as instructed: 80 EC, Choir blessing. Sevas is 
  "handled." Brother Enn's operation continues.
- Deliver to Scrolls or Liora as Sevas requests: No Choir payment. Possible reward 
  from Scrolls/Liora. Choir standing drops. Enn's operation unravels over months.
- Keep the ledger: Very risky, very valuable, makes three parties unhappy.

DM NOTE: Do not push the party toward any outcome. Let them make the call.
```

Notice: every option is described with specific consequences, specific names, specific timeline. Not "good" or "bad" outcomes — just different ones with real costs and real gains.

---

## Scene Writing

### Scene Description (Not Read-Aloud)

Never write "READ ALOUD" text. Write **Scene Description** — 2-3 sentences the DM paraphrases. Not scripted. Not verbatim.

```
❌ BAD (read-aloud style):
"You enter the warehouse. The smell of old paper and copper coins fills your nostrils 
as dust motes drift through a single shaft of light. Somewhere deeper inside, you hear 
a door close..."

✅ GOOD (scene description for DM to paraphrase):
Scene: The counting house is quiet for the hour — Tarn dismissed two clerks before 
the party arrived. The single lit lantern on the desk is positioned to leave her face 
partially in shadow. She is not surprised they came.
```

### Opening Scene Formula (from real Floor modules)

Strong opening scenes have three beats:

1. **Environmental detail that signals something is wrong** (not "there is danger" — a specific observable detail)
2. **An NPC reaction that tells players they are expected or recognized** (without explaining why)
3. **The immediate problem that requires a decision** (not a combat encounter — a situation)

```
✅ GOOD (from FLOOR 3 — The Day The Wall Held):
The walls are taller. The stakes are doubled. The watchtowers have two soldiers 
where there used to be one. The sky to the east is wrong — too much smoke, too low 
on the horizon to be sunrise. A soldier sees them and his face does something 
complicated. Not surprise. Not relief. Recognition. "They said you'd be back," he says.
He doesn't explain who he means. He doesn't need to.
```

Three beats, all observable. No exposition. The reader fills in meaning from specific details.

### Dialogue Rules

NPCs do not make speeches. They make statements that prompt questions.

```
❌ BAD:
"Let me explain the full situation to you," said Sir Alard Montreval. "The enemy has 
been building their forces for years and the Empire was too arrogant to listen to my 
warnings. Now the wall may fall and we need your help to stop them at the docks."

✅ GOOD (from real Floor module):
"The wall will hold or it won't. I have done everything I can for it."
"The ship is the problem no one at this table wants to name."
"If BLACKWAKE reaches the bay and unloads, we fight on two fronts. We lose on two fronts."
He looks at the party directly. "You know what it can do."
```

Four sentences. No exposition. Every sentence is a prompt. The party has questions now — which is the point.

**Rule: 2-3 lines of actual NPC dialogue, then the NPC waits for the party to respond.**

---

## Encounter Design

### Combat Encounters

```
❌ BAD:
4 guards (Guard stat block) attack the players.

✅ GOOD:
Warehouse Ambush
Setup: Two guards visible at the door. Two more hidden behind crates (DC 14 Perception).
Visible guards stall while hidden ones flank. They know the layout; party does not.
Terrain: Crates provide half cover. Lantern oil on floor (5-ft square) can be ignited.
Catwalk above — injured guards retreat there if they lose initiative.
Morale: Fight until two are down, then flee to warn the boss. If one escapes, 
the boss has 1d4 minutes to prepare.
Loot: 12 EC each. One carries a Consortium badge — incriminating if kept, valuable 
if returned.
```

### Social Encounters

```
❌ BAD:
DC 15 Persuasion to convince Tarn.

✅ GOOD:
Vella Tarn's Office
Setup: Tarn expects trouble. Hand near concealed crossbow. Two bodyguards by the door.
She'll hear them out — this meeting is a test and she has already decided that.
The test: She asks them to name their price. Too little = hiding something. 
Too much = greedy and unreliable.
The right answer: Ask for information instead of money. She respects long-term thinking.
If attacked: Floor trap (DC 14 DEX, fall 2d6 bludgeoning). Bodyguards cover her escape.
If negotiated well: Reveals the real target — her own superior, who she suspects of treason.
```

---

## Anti-Patterns (NEVER DO THESE)

### Purple Prose
```
❌ "The ethereal glow of the bioluminescent fungi cast an otherworldly pallor 
    across the shadowy depths of the forgotten passageway."
✅ "The fungi gave off enough light to see by — barely. The tunnel smelled like 
    wet stone and something dead."
```

### Telling Not Showing
```
❌ "Wex is nervous and guilty-looking."
✅ "Wex refills your drink before it's half empty. He hasn't met your eyes since 
    you sat down."
```

### Scripted Outcomes
```
❌ "The players successfully negotiate and Wex hands over the disc."
✅ "If the party offers specific reassurance (not vague): Wex goes quiet for a 
    moment, then reaches into his coat. 'I was going to return it anyway,' he says. 
    Nobody at the table believes him. He probably doesn't either."
```

### Hedging Language
```
❌ "The figure seemed to be watching them. It appeared to move."
✅ "The figure was watching them. It moved."
```

### Vague Locations
```
❌ "a warehouse", "some guards", "a district"
✅ "Consortium Counting House #3 on Cobbleway", "two Iron Fang enforcers on 
    rotating eight-hour shifts", "the Collapsed Plaza, Warrens"
```

### Villains Without Reasons
```
❌ "The cult leader has been corrupting townsfolk."
✅ "Thane is not lying to his followers. He believes completely. Something is 
    communicating through him — not the god he thinks it is. He is genuinely devout 
    and genuinely deceived. That makes him more dangerous, not less."
```

---

## Boon / Powerful NPC Reward Design

When a powerful NPC (deity, faction leader, faction patron) offers aid or reward, the structure is:
- **Watches for:** ONE specific player behavior — not general virtue
- **Boon:** Mechanical benefit tied to that behavior
- **Price:** Something that creates a future plot thread

```
✅ GOOD (from Floor 3 — Tyr):
WATCHES: The player who protects someone at personal cost.
         Tyr does not care about winning. He cares about who you were willing to lose for.
BOON: Once per long rest — add 1d8 radiant or take advantage when protecting another creature.
PRICE: After the floor, the player must speak Montreval's name aloud in a public Tower space.
       Not a prayer. Just ensuring someone outside the floor knows what happened to him.
DM NOTE: The boon is easy. The price is the hook. Speaking the name publicly means 
         Thesaurus logs it, factions note it, and one party member becomes narratively significant.
         Tyr knows this. He considers it a fair trade.

✅ GOOD (from Floor 3 — Anansi):
WATCHES: Whoever lies to an enemy in a technically-true way. Anansi appreciates the 
         technically-true lie more than any other form of deception.
BOON: Once per floor — ask Anansi about any NPC's weakness, fear, or secret motivation.
      He will answer accurately in riddle, story, or seemingly unrelated observation.
PRICE: Anansi will later retell a story the player gives him — to the faction that will find 
       it most politically inconvenient. Completely accurate, framed to look morally questionable.
       He does not do this out of malice. He does it because that makes it a good story.
       The party cannot be angry. This is explicitly what they agreed to.
```

**Rules for boon/price design:**
1. What the NPC watches for must be observable behavior — not an alignment or a general virtue
2. The boon should mechanically reflect that behavior (Tyr → protection boon; Anansi → information boon)
3. The price must create forward motion — a future encounter, a faction note, a thread the DM files
4. The NPC is not trying to harm the party. They have their own goals. The price is the intersection.

---

## Rewards Section

```
❌ BAD:
Players get 200 EC and a magic sword.

✅ GOOD:
Base: 80 EC from Brother Enn on return of the ledger
Choir Blessing: 1 use — advantage on one save, or +2 to one skill check (declared before rolling)
Faction: Choir standing +1 if ledger returned intact and cleanly
Story unlock: Brother Enn becomes a known contact. His nervousness during handoff 
is observable (Insight DC 13 — he is afraid of what they may have read).

If Ledger Delivered to Liora Instead:
Choir standing → Unfriendly
Tower Authority opens quiet investigation (surfaces in 2-3 posting periods)
Liora becomes a high-value contact with Tower Authority access
Sevas sends a message: "Thank you."
```

---

## Banned Phrases

Cut these on sight:
- "It is worth noting that..."
- "Needless to say..."
- "A sense of mystery..."
- "An air of danger..."
- "In conclusion..."
- "As the saying goes..."
- "The players will feel..."
- "This creates an atmosphere of..."
- "Things take a dark turn when..."

---

## Quick Reference

| Element | Standard |
|---------|----------|
| **Overview** | Surface problem + real truth + hidden stakes |
| **Background** | NPC specific reason, not "they're corrupt" |
| **NPCs** | Specific want + specific hidden + specific trigger |
| **Dialogue** | 2-3 lines max, then NPC waits |
| **Scenes** | 2-3 sentences DM paraphrases, not scripted |
| **Encounters** | Setup + terrain + morale + loot |
| **Resolution** | Non-combat path first, always |
| **Moral choice** | ≥1 per posting with no clean outcome |
| **DM Note** | Tone + risk + recurring flag + thread flag |
| **Hook** | One specific future seed |
| **Sympathetic villain** | Specific grievance + physical evidence trail |
| **Environmental tells** | 2-3 objects in NPC space that answer questions |
| **Reveal scene** | Trust must be real before deception lands |
| **Boon/price** | Observed behavior → mechanical reward → future thread |

**The Undercity is a real place with real people making real decisions under real pressure. Write it that way.**
