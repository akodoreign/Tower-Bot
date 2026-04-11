---
name: module-quality
description: "Quality patterns for D&D mission modules. Use when generating mission module content via ProAuthorAgent, DNDExpertAgent, DNDVeteranAgent, or mission_compiler.py. Contains concrete patterns, good/bad examples, and anti-patterns to enforce professional module quality."
---

# Module Quality Patterns

## Purpose

This skill encodes patterns from professional D&D modules to ensure generated content matches published quality. Inject relevant sections into agent system prompts.

---

## Section Patterns

### Overview Section

**Purpose:** One-paragraph hook + context for DM.

```
❌ BAD:
This mission involves investigating something bad in a warehouse. The 
players will need to find clues and fight enemies. There may be 
complications along the way.

✅ GOOD:
Someone inside the Consortium's Cobbleway counting house has been 
skimming — badly. Guildmaster Dhal discovered three separate ledgers 
with three different totals and wants answers before the quarterly 
audit. The players are hired as outside investigators because Dhal 
can't trust his own people. What they uncover goes deeper than simple 
embezzlement: the missing funds trace to weapons shipments destined 
for the Warrens.
```

**Pattern:**
1. What's the problem (specific)?
2. Who hired them and why?
3. What's the hidden truth (DM-only)?

---

### Act Structure (Act 1, 2, 3)

**Purpose:** Playable scenes with read-aloud text, DM guidance, and branches.

#### Read-Aloud Text Rules

- Present tense, second person
- Sensory, not explanatory
- Never reveals hidden information
- 3-5 sentences max

```
❌ BAD:
You enter the warehouse. It is dark and scary. There might be enemies 
hiding. The warehouse is owned by the Consortium.

✅ GOOD:
The Consortium counting house smells like old paper and copper coins. 
Dust motes drift through the single shaft of light from a high window. 
Your footsteps echo off the stone floor. Somewhere deeper inside, a 
door closes.
```

#### Location Entry Format

```
### [LOCATION NAME]

> *Read-aloud text here.*

**Features:** [Physical details the DM needs]
**Hazards:** [Environmental dangers, if any]
**Hidden:** [DC X to spot Y]
**NPCs Present:** [Who is here, what they're doing]
**If combat starts:** [Tactical notes]
```

#### NPC Box Format

```
**[NAME]** — [Role]
- **Appearance:** 2-3 visual details
- **Voice:** How they talk
- **Knows:** Information they have
- **Wants:** What they're after
- **If threatened:** Response
- **If charmed:** Response
```

---

### Encounter Design

**Purpose:** Combat and social encounters that play well at the table.

#### Combat Encounters

```
❌ BAD:
4 guards (Guard stat block) attack the players.

✅ GOOD:
**Warehouse Ambush**
- **Setup:** Two guards visible at the door. Two more hidden behind 
  crates (DC 14 Perception to spot). Visible guards stall while 
  hidden ones flank.
- **Terrain:** Crates provide half cover. Lantern oil on floor 
  (5-foot square) can be ignited. Catwalk above — injured guards 
  retreat there.
- **Morale:** Guards fight until two are down, then flee to warn 
  the boss.
- **Loot:** Each guard carries 12 EC and a Consortium badge.
```

#### Social Encounters

```
❌ BAD:
DC 15 Persuasion to convince the NPC.

✅ GOOD:
**Vella Tarn's Office**
- **Setup:** Tarn expects trouble. Hand near concealed crossbow. 
  Two bodyguards by the door.
- **The Test:** She'll ask them to name their price. Too little = 
  hiding something. Too much = greedy and unreliable.
- **The Right Answer:** Ask for information instead of money. She 
  respects long-term thinking.
- **If attacked:** Floor trap (DC 14 DEX or fall 2d6).
- **If negotiated well:** Reveals the real target — her own superior.
```

---

### Rewards Section

**Purpose:** Clear, structured rewards and consequences.

```
❌ BAD:
Players get 200 EC and a magic sword.

✅ GOOD:
**Base:** 200 EC from Vella Tarn
**Discretion bonus:** +50 EC if no witnesses
**Evidence bonus:** +100 EC if ledger pages recovered
**Faction:** Iron Fang Consortium reputation +1 tier
**Unlock:** Vella becomes a contact for direct Consortium missions

**If Failed:**
- Consortium reputation -1 tier
- The traitor escapes — reappears as enemy in future mission
- Vella is demoted; replacement is hostile to adventurers
```

---

## Anti-Patterns (NEVER DO THESE)

### Purple Prose
```
❌ "The ethereal glow of the bioluminescent fungi cast an otherworldly 
    pallor across the shadowy depths of the forgotten passageway."
✅ "The fungi on the ceiling gave off enough light to see by — barely. 
    The tunnel smelled like wet stone and something dead."
```

### Echo Chamber
```
❌ "The market was busy and crowded. Throngs of people packed the 
    aisles. The dense crowd made movement difficult."
✅ "The market was packed. A child knocked over a basket of dried 
    fish and kept running."
```

### Hedging
```
❌ "The figure seemed to be watching them. It appeared to move closer."
✅ "The figure was watching them. It moved closer."
```

### Adjective Avalanche
```
❌ "The dark, shadowy, mysterious, ancient corridor..."
✅ "The corridor stretched into darkness."
```

### Generic Locations
```
❌ "a warehouse", "some guards", "a district"
✅ "Consortium Counting House #3 on Cobbleway", "two Lotus enforcers"
```

### Scripted Dialogue
```
❌ "I believe we should investigate the warehouse," said Marcus.
✅ "The warehouse," Marcus said. "Has to be. They wouldn't—" He 
    stopped. "You hear that?"
```

---

## Banned Phrases

These phrases add nothing. Cut them:

- "It is worth noting that..."
- "Interestingly enough..."
- "As the saying goes..."
- "Needless to say..."
- "At the end of the day..."
- "In conclusion..."
- "It goes without saying..."
- "A sense of..."
- "An air of..."

---

## DM Boxes and Tips

Use GM Notes for practical advice:

```
> **DM TIP:** If players bypass the ambush, have the guards appear 
> later as reinforcements during the boss fight.
```

```
> **DM NOTE:** The puzzle has two solutions. Don't hint at the 
> second unless players are stuck for 10+ minutes.
```

---

## Tables for Randomization

Include d4/d6/d8 tables for:
- Random rumors (one true, rest false)
- Complications (what goes wrong)
- Environmental effects
- NPC reactions

```
**d6 Complications**
1. Warden patrol passes by. Players must hide or explain.
2. A secondary faction arrives with the same objective.
3. The target isn't here — they left an hour ago.
4. Fire breaks out. 1d4 rounds before it spreads.
5. An innocent bystander is caught in the crossfire.
6. The players' contact sold them out.
```

---

## Injection Snippets

### For ProAuthorAgent (narrative)

```
ANTI-PATTERNS (NEVER USE):
- Purple prose ("ethereal glow", "otherworldly pallor")
- Echo chamber (saying same thing three ways)  
- Hedging ("seemed to", "appeared to", "might be")
- Adjective avalanche (more than one adjective per noun)
- Generic locations ("a warehouse" → name it specifically)

REQUIRED:
- Specific names, numbers, times, locations
- Sensory grounding (what characters physically experience)
- Read-aloud text in present tense, second person
- Short sentences for action, varied length for description
```

### For DNDExpertAgent (mechanics)

```
ENCOUNTER FORMAT:
- Setup (who, where, starting positions)
- Terrain (cover, hazards, tactical features)
- Morale (when they flee, surrender, or fight to death)
- Loot (specific items, specific EC amounts)

CREATURE STATS MUST INCLUDE:
- Tactics (how they fight, who they target)
- Special abilities with triggers
- Legendary actions for CR 8+ creatures
```

### For DNDVeteranAgent (locations/atmosphere)

```
LOCATION FORMAT:
### [LOCATION NAME]
> *Read-aloud text (3-5 sentences, sensory, present tense)*

**Features:** [Physical details]
**Hazards:** [Environmental dangers if any]
**Hidden:** [DC X to spot Y]

RUMOR/ENCOUNTER TABLES:
- d6 or d8 format
- One true rumor, rest false or misleading
- Complications that create choices, not roadblocks
```

---

## Quick Reference

| Element | Rule |
|---------|------|
| Read-aloud | Present tense, sensory, no hidden info |
| Locations | Name specifically, include terrain/hazards |
| NPCs | Appearance, voice, knows, wants, reactions |
| Encounters | Setup, terrain, morale, loot |
| Rewards | Base + bonus + faction + unlock |
| Consequences | Faction + NPC + world + personal |
| Tables | d4/d6/d8, short entries, one truth among lies |

**The Undercity is a real place. Write like you live there.**
