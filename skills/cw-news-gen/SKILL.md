---
name: cw-news-gen
description: "Creative writing skill for generating Undercity Dispatch news bulletins. Use when writing prompts for news_feed.py or when the bot generates hourly bulletins. Contains the Dispatch house style, bulletin structure, common failures to avoid, and examples of good vs bad bulletins."
---

# Creative Writing — News Bulletin Generation

## The Undercity Dispatch House Style

The Undercity Dispatch is the city's primary news feed. It's read by everyone from Guild Spire executives to Warrens scavengers. It has a distinctive voice:

### Core Attributes

| Attribute | Description |
|-----------|-------------|
| **Tone** | Cynical, wry, matter-of-fact. The reporter has seen everything. Nothing surprises them anymore. |
| **Length** | 3-6 lines. Never longer. Bulletins, not articles. |
| **Specificity** | Names, places, numbers. Never vague. "47 EC" not "some coins." |
| **Stance** | Reports, doesn't judge. The Dispatch isn't propaganda — it just tells you what happened. |
| **Humor** | Dark, dry, gallows. Never forced. The humor emerges from the absurdity of life in the Undercity. |

---

## Bulletin Structure

Every bulletin follows this pattern:

```
[EMOJI] **[HEADLINE — Location or Subject]**
[2-4 lines of grounded, specific content]
[Optional: faction response, witness quote, or consequence]
-# *— [TNN sign-off]*
```

### Example Structure

```
📰 **Markets Infinite — Consortium Warehouse Fire**
The Iron Fang Consortium's secondary warehouse on Cobbleway Market burned 
to the foundation last night. Cause unknown. Three workers hospitalised 
with smoke inhalation. Consortium spokesperson Vella Tarn called it "an 
unfortunate accident" — twice, unprompted.
-# *— TNN Field Correspondent*
```

---

## Bulletin Types — How Each Should Sound

### Hard News (Breaking Events)

Short, punchy, factual. The reporter just arrived at the scene.

```
✅ GOOD:
🔥 **Outer Wall — Breach Alarm, Wall Quadrant C**
Wardens locked down a 200-metre section of the Outer Wall at third watch. 
Captain Korin was seen entering the cordoned zone with a full containment 
squad. No official statement. The lockdown remains in effect.
-# *— TNN Breaking*

❌ BAD:
🔥 **Outer Wall Chaos**
Something terrible happened at the Outer Wall! The brave Wardens rushed 
to contain the mysterious threat as fear gripped the hearts of all who 
witnessed the dark portent of things to come...
```

The bad example has no specifics, purple prose, and editorializes.

### Faction News (Political/Guild)

Knowing. Skeptical. Reading between the lines.

```
✅ GOOD:
🏛️ **Grand Forum — Serpent Choir Contract Dispute**
High Apostle Yzura has formally rejected the Consortium's contract renewal 
offer for Sanctum Quarter divine licensing. Terms were not disclosed, but 
sources close to both parties used the word "insulting." The previous 
contract expires in eighteen days.
-# *— TNN Political Desk*

❌ BAD:
🏛️ **Religious Drama Unfolds!**
In a shocking turn of events, the powerful religious faction has clashed 
with the merchant guild in what promises to be an epic battle of wills 
that will shake the very foundations of the city's economy!
```

### Human Interest (Street-Level)

Warm, specific, one person's small story.

```
✅ GOOD:
👤 **Warrens — The Cobbler Who Won't Quit**
Mira Voss has repaired shoes in the same Echo Alley stall for 34 years. 
Last week someone stole her tools. This week she's back, working with 
borrowed awls and a hammer she made from scrap. "Feet still hurt," she 
said. "Boots still break. What else would I do?"
-# *— TNN Street Beat*

❌ BAD:
👤 **Heartwarming Story of Resilience**
In a touching display of the human spirit, a humble cobbler demonstrates 
that hope springs eternal even in the darkest corners of our city, proving 
that determination can overcome any obstacle...
```

The bad example tells us what to feel instead of showing us Mira.

### Rumour/Gossip

Uncertain. Source-attributed. Lets the reader decide.

```
✅ GOOD:
👁️ **Neon Row — Whispers About the Night Pits**
Three separate sources claim Sable has been meeting with someone from the 
Serpent Choir. None would say more. The Lotus denies any contract 
negotiations. The Choir declined to comment. Sable laughed when asked 
and walked away.
-# *— TNN Street Sources*

❌ BAD:
👁️ **Secret Dealings Exposed!**
Shadowy meetings between mysterious figures suggest dark alliances are 
being forged in the underground! What sinister plots are being hatched?
```

The bad example is vague and melodramatic. The good example gives specifics while acknowledging uncertainty.

---

## Common Failures — What Breaks Bulletins

### 1. The Title-Only Bulletin

Sometimes the AI returns just a title with no content:

```
❌ BROKEN:
Lost Kitten: The Shadow's Whisker.
```

This happens when the prompt is unclear or the AI misunderstands the task. A valid bulletin MUST have at least 2-3 lines of content after the headline.

**Fix:** Add explicit minimum length requirements to prompts.

### 2. The Purple Prose Flood

```
❌ BROKEN:
As the ethereal glow of the bioluminescent fungi cast their otherworldly 
pallor across the shadowy depths of the forgotten marketplace, whispers 
of ancient secrets mingled with the musty scent of intrigue and mystery...
```

This is atmosphere-flavored nothing. No facts, no names, no story.

**Fix:** Require at least one named NPC, one specific location, and one concrete event.

### 3. The Preamble Problem

```
❌ BROKEN:
Sure! Here's a bulletin for you:
📰 **Markets Infinite — Price Surge**
...
```

The AI prepends assistant-style preambles.

**Fix:** Strip lines starting with "Sure", "Here's", "Certainly", etc.

### 4. The Sign-Off Slap

```
❌ BROKEN:
...The city watches. May the spirits guide you.
The Oracle has spoken.
```

The AI appends unnecessary sign-offs or blessings.

**Fix:** Strip lines with "may the", "the city watches", "oracle", etc.

### 5. The Rate Table Leak

```
❌ BROKEN:
📰 **Economy Update**
New Essence Coin prices:
1 EC = 0.0038 Kharma
100 EC = 0.38 Kharma
...
```

The AI generates exchange rate tables even when told not to.

**Fix:** Explicit negative instruction + post-processing regex filter.

---

## Prompt Engineering for Bulletins

### Essential Elements

Every bulletin prompt should include:

1. **World context** — Brief lore block so the AI knows the setting
2. **Bulletin type** — What kind of story to write
3. **Recent memory** — Last 5-10 bulletins for continuity
4. **Live NPC roster** — Names the AI can use
5. **Explicit constraints** — Length, format, what NOT to do
6. **Negative examples** — Show common failures to avoid

### Constraint Block Template

```
RULES — READ ALL OF THESE:
- Output the bulletin and NOTHING ELSE. No preamble, no sign-off.
- Do NOT start with "Sure!", "Here's a bulletin:", or any opener.
- Do NOT end with "May the spirits..." or any sign-off.
- 3-6 lines maximum. Punchy. Specific.
- Use at least one named NPC from the roster.
- Use at least one specific location from the gazetteer.
- Ground everything in this specific city. No generic fantasy.
- If your response contains anything other than the bulletin, you have failed.
```

### The "You Have Failed" Pattern

Ending prompts with "If X, you have failed" improves compliance. The AI treats it as a hard constraint rather than a suggestion.

---

## Post-Processing Checklist

After generating a bulletin, apply these filters:

1. **Strip preambles** — Remove lines starting with "Sure", "Here", "Certainly"
2. **Strip sign-offs** — Remove lines with "may the", "city watches", "oracle"
3. **Strip rate tables** — Remove lines matching EC/Kharma rate patterns
4. **Validate length** — Warn if < 2 lines or < 50 characters
5. **Add timestamp** — Prepend dual-timestamp header
6. **Add TNN sign-off** — Append random TNN attribution
7. **Run editor pass** — Second AI pass for continuity/fact-check

---

## Example Prompts

### Good Prompt Structure

```python
prompt = f"""
{WORLD_LORE_BLOCK}  # Setting, factions, tone

RECENT BULLETINS (for continuity):
{recent_memory}

LIVE NPCs (use these names):
{npc_roster_block}

LIVE LOCATIONS (use these places):
{gazetteer_block}

---
TASK: Write ONE Undercity Dispatch bulletin of type: {bulletin_type}

RULES:
- Output ONLY the bulletin. No preamble, no sign-off.
- 3-6 lines maximum.
- Use at least one named NPC from the roster.
- Use at least one specific location.
- Ground everything in this city. No generic fantasy.
- If your response contains anything other than the bulletin, you have failed.
"""
```

### Testing Bulletin Quality

A good bulletin should pass these checks:

- [ ] Contains at least one specific location name
- [ ] Contains at least one specific NPC name OR concrete detail
- [ ] Is 3-6 lines (not 1, not 10)
- [ ] Has no preamble ("Sure!", "Here's...")
- [ ] Has no sign-off blessing ("May the spirits...")
- [ ] Sounds like a reporter wrote it, not a novelist
- [ ] Something actually happened (not just "whispers of mystery")

---

## Quick Reference Card

| Element | Rule |
|---------|------|
| **Length** | 3-6 lines, never more |
| **Tone** | Cynical, wry, matter-of-fact |
| **Specificity** | Names, places, numbers — always |
| **Headlines** | Bold, location-tagged |
| **Emoji** | One relevant emoji at start |
| **Sign-off** | TNN attribution (added in post-processing) |
| **No** | Preambles, blessings, purple prose, rate tables |

**Remember: The Dispatch reports. It doesn't dramatize, moralize, or editorialize.**
