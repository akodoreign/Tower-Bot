# Mission Builder Refactoring: Dynamic Mission Types & Difficulty Ratings

## Overview

The mission builder has been refactored from a static, generic system to a **dynamic, type-aware generation system** that leverages creative writing skills. This refactoring introduces:

1. **18 Dynamic Mission Types** — Each with unique structure, guidance, and skill requirements
2. **1-10 Difficulty Scale** — Replaces "easy/medium/hard/deadly" with epic scale
3. **Title Integration** — Mission types incorporated into generated titles
4. **Creative Writing Skills Integration** — Dynamic generation based on mission characteristics
5. **Full Backward Compatibility** — Existing code works unchanged

---

## What Changed

### 1. New Mission Types (18 Total)

Located in: `src/mission_builder/mission_types.py`

Each mission type defines:
- **Description**: What this mission type is
- **DM Guidance**: How to run this type effectively
- **Typical Act Structure**: Expected pacing and flow
- **Resolution Keywords**: Success/failure language
- **Combat/Roleplay Intensity**: How action-heavy vs. dialogue-heavy
- **Skill Checks**: Common checks needed
- **Suggested Skills**: Creative writing skills path

**Available Types:**
- `escort` — Protect and transport a target
- `recovery` — Find and retrieve something
- `investigation` — Uncover a mystery
- `battle` — Direct combat confrontation
- `ambush` — Respond to surprise attack
- `negotiation` — Resolve conflict diplomatically
- `theft` — Steal something guarded
- `rescue` — Save someone from danger
- `exploration` — Discover new areas
- `discovery` — Find clues or knowledge
- `delivery` — Transport safely to destination
- `sabotage` — Disable/destroy target
- `infiltration` — Enter restricted area secretly
- `assassination` — Eliminate target (complex)
- `defense` — Protect location from attack
- `puzzle` — Solve complex mystery/trap
- `gathering` — Collect resources
- `political` — Navigate faction dynamics

### 2. Difficulty Scale: 1-10 (Easy → Epic)

**Old System:**
```
easy → medium → hard → deadly
```

**New System:**
```
1: Trivial        5: Hard           9: Catastrophic
2: Easy           6: Dangerous      10: Epic
3: Moderate       7: Deadly
4: Challenging    8: Extreme
```

**Mapping:**
- **Difficulty → Tier**: Maps to mission tiers (local, patrol, standard, etc.)
- **Difficulty → 5e**: Maps to D&D 5e difficulty (easy, medium, hard, deadly)
- **Difficulty → Description**: Human-readable string

### 3. Schema Updates

**MissionMetadata now includes:**
- `difficulty_rating` (int 1-10) — New primary difficulty field
- `mission_type` (str) — Updated with 18 new types

**Encounter now includes:**
- `difficulty_rating` (int 1-10) — Replaces old difficulty field
- Old `difficulty` field kept for backward compatibility

### 4. Title Generation

New system automatically incorporates mission type into titles:

**Before:**
```
"The Silent Vault"
"Counting House Discrepancy"
```

**After:**
```
"Theft: The Silent Vault"
"Investigation: The Counting House Discrepancy"
"Deadly Rescue: Save the Captive"
```

Format: `[DIFFICULTY] [TYPE]: [SUBJECT]`

Optional: Uses creative writing skills for more varied titles via LLM

### 5. Dynamic Generation

Mission generation now:
1. **Determines mission type** from input or tier
2. **Enhances titles** with mission type
3. **Adjusts system prompt** for mission-specific guidance
4. **Uses skills integration** for more dynamic content
5. **Sets metadata** with difficulty_rating and mission_type

---

## File Changes

### New Files

**`src/mission_builder/mission_types.py`** (900+ lines)
- Complete mission type definitions  
- Difficulty mapping functions
- Dynamic title generation
- DM guidance for each type
- Skill recommendations
- Act structure templates

### Modified Files

**`src/mission_builder/schemas.py`**
- Added `difficulty_rating` to MissionMetadata
- Updated `mission_type` options (18 types)
- Added `difficulty_rating` to Encounter
- Maintained backward compatibility

**`src/mission_builder/json_generator.py`**
- Import mission types module
- Add mission type context to generation
- Enhance titles with mission types
- Pass difficulty_rating through system
- Log mission type and difficulty

**`src/mission_builder/api.py`**
- Add `difficulty_rating` parameter (Optional[int])
- Pass difficulty_rating through generation pipeline
- Clamp difficulty to 1-10 range
- Default to 5 (Challenging) if not specified

---

## Usage Examples

### Basic Mission Generation

```python
from src.mission_builder import generate_mission

# With mission type and difficulty rating
module = generate_mission(
    title="The Silent Vault",
    faction="Glass Sigil",
    tier="high-stakes",
    body="Glass Sigil needs trustworthy adventurers to steal...",
    mission_type="theft",
    player_name="Party of Shadows",
    reward="1000 EC + faction favor",
    difficulty_rating=7,  # Deadly
)

# Title will be auto-enhanced to: "Deadly Theft: The Silent Vault"
print(module["metadata"]["title"])
# → "Deadly Theft: The Silent Vault"

# Mission type in metadata
print(module["metadata"]["mission_type"])
# → "theft"

# Difficulty rating in metadata
print(module["metadata"]["difficulty_rating"])
# → 7
```

### All Mission Types

```python
from src.mission_builder.mission_types import list_mission_types, get_mission_type

# List all available types
types = list_mission_types()
# → ["ambush", "assassination", "battle", "delivery", ...]

# Get specific type
mission = get_mission_type("investigation")
print(mission.dm_guidance)
# → "This is detective work. Provide 3-4 clue locations..."
```

### Difficulty Scale

```python
from src.mission_builder.mission_types import (
    get_difficulty_description,
    map_difficulty_to_tier,
    map_difficulty_to_5e,
)

# Human-readable description
desc = get_difficulty_description(7)
# → "Deadly — PC likely to die, retreat recommended"

# Map to tier
tier = map_difficulty_to_tier(7)
# → "major"

# Map to D&D 5e difficulty
d5e = map_difficulty_to_5e(7)
# → "deadly"
```

### With Creative Writing Skills

```python
from src.mission_builder import generate_mission
from src.mission_builder.json_generator import set_use_skills

# Enable skills for enhanced generation
set_use_skills(True)

module = generate_mission(
    title="Counting House Discrepancy",
    faction="Iron Fang Consortium",
    tier="investigation",
    mission_type="investigation",
    difficulty_rating=4,  # Challenging
    body="Consortium auditors found discrepancies in three ledgers...",
)

# Titles will now use creative writing skills for variation
# More atmospheric and compelling generation
```

---

## Breaking Changes

**NONE** — Full backward compatibility maintained!

### Old Code Still Works

```python
# Old format still generates missions
module = generate_mission(
    title="My Mission",
    faction="Some Faction",
    tier="standard",
    body="Do this job",
)
# → Works! Uses defaults: mission_type defaults to tier, difficulty_rating defaults to 5

# If mission_type not specified, uses tier name
# If difficulty_rating not specified, uses 5 (Challenging)
# Title enhancement happens automatically
```

### Migration Path

Existing code doesn't need changes, but you can gradually adopt:

```python
# Before (still works):
mission = generate_mission(title="X", faction="Y", tier="Z", body="Do it")

# After (recommended - more specific):
mission = generate_mission(
    title="X",
    faction="Y",
    tier="Z",
    body="Do it",
    mission_type="investigation",
    difficulty_rating=6,  # Dangerous
)
```

---

## How It Works

### Title Enhancement Flow

1. **Input**: `title="Vault Heist"`, `mission_type="theft"`, `difficulty=7`
2. **Check**: Does title already contain mission type? No.
3. **Generate**: If skills enabled, use LLM + creative writing skills
4. **Template**: Fall back to format if LLM fails
5. **Output**: `"Deadly Theft: Vault Heist"`

### Mission Type System Prompt Integration

When generating module content:

1. **Extract mission type** from mission dict
2. **Get mission type definition** from mission_types.py
3. **Enhance system prompt** with type-specific guidance
4. **Pass to LLM** with mission-aware context
5. **Output** reflects mission type structure (acts, encounters, etc.)

### Difficulty Rating Usage

1. **Difficulty 1-10** set in mission metadata
2. **Clamped** to 1-10 (invalid values corrected)
3. **Stored** in MissionModule metadata
4. **Logged** for visibility ("Difficulty: 7/10")
5. **Available** for future calculations (CR, XP, etc.)

---

## Examples by Mission Type

### Escort Mission
```python
module = generate_mission(
    title="Protect the Magistrate",
    faction="Wardens of Ash",
    mission_type="escort",
    difficulty_rating=5,  # Hard
)
# Generated title: "Hard Escort: Protect the Magistrate"
# Acts focus on: Meeting → Route Selection → Threats → Safe Arrival
```

### Investigation
```python
module = generate_mission(
    title="Counting House Discrepancy",
    faction="Iron Fang Consortium",
    mission_type="investigation",
    difficulty_rating=4,  # Challenging
)
# Generated title: "Challenging Investigation: The Counting House Discrepancy"
# Acts focus on: Briefing → 3 Investigation Leads → Revelation → Confrontation
```

### Theft
```python
module = generate_mission(
    title="Vault Heist",
    faction="Obsidian Lotus",
    mission_type="theft",
    difficulty_rating=7,  # Deadly
)
# Generated title: "Deadly Theft: The Vault Heist"
# Acts focus on: Planning → Infiltration → Heist → Escape
```

### Battle
```python
module = generate_mission(
    title="Face the Rift Incursion",
    faction="Argent Blades",
    mission_type="battle",
    difficulty_rating=6,  # Dangerous
)
# Generated title: "Dangerous Battle: Face the Rift Incursion"
# Acts focus on: Encounter → Tactics → Escalation → Victory
```

---

## Integration with Creative Writing Skills

### Mission Type DM Guidance

Each mission type includes `dm_guidance` that's incorporated into the system prompt:

```
MISSION TYPE: Investigation
Uncover a mystery by gathering clues and interrogating suspects.

DM GUIDANCE FOR THIS TYPE:
This is detective work. Provide 3-4 clue locations, each with multiple approaches...
```

### Suggested Skills Path

Each mission type recommends which skills to leverage:

```python
mission = get_mission_type("theft")
print(mission.suggested_skills)
# → ["mission-gen", "prose-writing"]

# System uses these when building prompts to enhance quality
```

### Dynamic Title Generation

If `use_skills=True`, titles use creative writing principles:

```
Format: [DIFFICULTY] [TYPE]: [SPECIFIC, GROUNDED SUBJECT]
- Specific: "The Counting House Discrepancy" (not "make more money")
- Grounded: Uses exact location names (Cobbleway Market)
- Intriguing: Makes player want to click/accept
```

---

## Testing

### Quick Verification

```python
# Test 1: Basic generation with new system
from src.mission_builder import generate_mission

module = generate_mission(
    title="Test Mission",
    faction="Iron Fang Consortium",
    tier="investigation",
    mission_type="investigation",
    difficulty_rating=5,
)

assert module is not None
assert "investigation" in module["metadata"]["mission_type"].lower()
assert module["metadata"]["difficulty_rating"] == 5
assert "Investigation" in module["metadata"]["title"]
print("✅ Test 1 passed: Basic generation works")

# Test 2: Mission type lookup
from src.mission_builder.mission_types import get_mission_type, list_mission_types

types = list_mission_types()
assert len(types) == 18
assert "investigation" in types
assert "theft" in types
print(f"✅ Test 2 passed: Found {len(types)} mission types")

# Test 3: Difficulty mapping
from src.mission_builder.mission_types import (
    map_difficulty_to_tier,
    map_difficulty_to_5e,
)

tier = map_difficulty_to_tier(5)
assert tier == "rift"
d5e = map_difficulty_to_5e(5)
assert d5e == "hard"
print("✅ Test 3 passed: Difficulty mapping works")

# Test 4: Backward compatibility
module_old = generate_mission(
    title="Old Style Mission",
    faction="Test",
    tier="standard",
    body="Test body",
)
assert module_old is not None
assert "standard" in module_old["metadata"]["mission_type"]
print("✅ Test 4 passed: Old-style calls still work")
```

---

## Next Steps

1. **Test end-to-end** mission generation with new types
2. **Monitor output quality** - Check if mission-aware prompts improve content
3. **Gather feedback** on difficulty ratings and title integration
4. **Extend**: Add more mission types if needed
5. **Optimize**: Fine-tune system prompts per mission type

---

## Summary

| Aspect | Before | After |
|--------|--------|-------|
| **Mission Types** | Generic/tier-based | 18 specific dynamic types |
| **Difficulty Scale** | 4-step (easy-deadly) | 10-step (trivial-epic) |
| **Title Integration** | Generic titles | Type-specific dynamic titles |
| **DM Guidance** | General | Mission-type-specific |
| **Skill Integration** | Limited | Full creative writing skills |
| **Backward Compatibility** | N/A | ✅ 100% maintained |

The system is now **more dynamic, more guided, and more interesting** while maintaining complete backward compatibility with existing code.
