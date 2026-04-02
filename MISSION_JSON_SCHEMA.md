# Mission JSON Schema Documentation

**Version 1.0** | Updated April 2026

## Overview

The Mission JSON Schema is the standardized output format for Tower of Last Chance mission modules. It replaces DOCX generation with structured JSON + image assets, enabling:

- **Programmatic access** to mission data
- **Multi-topic reuse** (VTT import, mobile apps, etc.)
- **Consistent structure** across mission types
- **Image asset organization** alongside content
- **Backward compatibility** with DOCX generation

## File Structure

```
generated_modules/<mission_id>/
├── module_data.json           # Main mission module (this schema)
├── room_info.json             # (dungeon-delve only) Detailed room data
├── composite_map.png          # (dungeon-delve) Full dungeon map
├── images/
│   ├── battle_map_1.png
│   ├── location_tavern.png
│   └── npc_captain.png
└── tiles/
    ├── room_01.png           # (dungeon-delve) Individual room tiles
    └── room_02.png
```

## Root Schema: MissionModule

```typescript
{
  // REQUIRED: Metadata about the mission
  metadata: {
    id: string                    // UUID
    title: string                 // "The Silent Vault"
    faction: string               // "Glass Sigil"
    tier: string                  // "high-stakes", "dungeon", etc.
    mission_type: string          // "standard", "dungeon-delve", "investigation"
    cr: number                    // Challenge Rating (0-30)
    party_level: number           // Expected party level (1-20)
    player_name: string           // "Unclaimed" or party name
    player_count: number          // Expected party size
    runtime_minutes: number       // 90, 120, 180, etc.
    reward: string                // "500 EC + 100 Kharma"
    generated_at: string          // ISO 8601 timestamp
    version: string               // "1.0"
  }

  // REQUIRED: Narrative content
  content: {
    overview: string              // Background and setup
    briefing?: string             // How players learn about mission
    act_1?: string                // Act 1 content
    act_2?: string                // Act 2 content
    act_3?: string                // Act 3 content
    act_4?: string                // Act 4 content  
    act_5?: string                // Act 5/resolution
    rewards_summary?: string      // Conclusion and rewards
  }

  // Optional: Encounters (combat, social, traps, etc.)
  encounters?: [
    {
      id: string                  // "enc_0"
      name: string                // "Cultist Ambush"
      type: string                // "combat", "social", "trap", "skill_challenge"
      difficulty: string          // "easy", "medium", "hard", "deadly"
      location: string            // Where it takes place
      description: string         // What happens
      creatures?: [
        {
          name: string
          cr: number
          hp: number
          ac: number
          count: number           // How many
          // Full D&D 5e stat block fields...
        }
      ]
      party_xp?: number
      tactics?: string            // Monster tactics
      loot?: [string]
    }
  ]

  // Optional: NPCs
  npcs?: [
    {
      id: string                  // "npc_0"
      name: string                // "Commander Kess"
      title: string               // "Iron Fang Captain"
      location: string            // Where usually found
      role: string                // "quest_giver", "ally", "enemy", "neutral"
      faction: string             // "Iron Fang Consortium"
      description: string         // Physical description + personality
      personality: [string]       // ["cautious", "honorable"]
      goals: [string]
      quotes: [string]            // Example dialogue
      relationships?: {
        "npc_1": "friendly"
        "npc_2": "rival"
      }
    }
  ]

  // Optional: Loot tables
  loot_tables?: [
    {
      id: string                  // "loot_0"
      name: string                // "Treasure Hoard"
      description: string
      rolls: number               // How many rolls (1, 2, 3)
      items: [
        {
          name: string
          rarity: string          // "common", "uncommon", "rare", etc.
          price: string           // "50 EC"
          count: number
          magical?: boolean
        }
      ]
    }
  ]

  // Optional: Image assets
  images?: [
    {
      id: string                  // "img_0"
      filename: string            // "images/battle_map_1.png"
      type: string                // "battle_map", "location", "creature", "npc_portrait"
      title: string
      description: string
      associated_encounter?: string  // "enc_0" if linked to encounter
    }
  ]

  // Optional: Named locations
  locations?: [
    {
      name: string                // "The Amber Tavern"
      type: string                // "tavern", "dungeon", "hideout", etc.
      district: string            // City district
      description: string
      history: string
      key_features: [string]      // ["fountain", "stage", "private room"]
      danger_level: string        // "low", "moderate", "high", "extreme"
      npcs: [string]              // NPC names found here
    }
  ]

  // Optional: Dungeon delve specific
  dungeon_delve?: {
    layout_name: string           // "5-room Dungeon"
    aesthetic: string             // "gothic", "natural", "arcane", etc.
    total_rooms: number
    entrance_room_id: string
    boss_room_id: string
    composite_map?: ImageAsset    // Reference to full map
    rooms: [
      {
        id: string                // "room_01"
        number: number            // 1, 2, 3, ...
        name: string              // "Entrance Hall"
        type: string              // "entrance", "chamber", "boss", etc.
        description: string       // Full room description
        features: [string]        // ["fountain", "pillars", "rubble"]
        exits: {
          north: string           // "room_02"
          east: string            // "room_03"
        }
        encounter?: Encounter     // Combat encounter (if any)
        treasure?: LootTable
        traps: [
          {
            name: string
            trigger: string       // What triggers it
            dc: number            // DC to avoid
            damage: string        // "2d6 piercing"
            effect: string        // What it does
          }
        ]
        secrets: [string]         // Hidden discoveries
        map_tile?: ImageAsset     // Reference to room tile image
      }
    ]
  }

  // Backward compat: DOCX sections (optional, for legacy tools)
  sections?: {
    overview?: string
    acts_1_2?: string
    acts_3_4?: string
    act_5_rewards?: string
  }
}
```

## Tier Enum

Valid tier values:
- `"local"` — Town-scale mission
- `"patrol"` — Patrol/scouting
- `"escort"` — Protection mission
- `"standard"` — Standard adventure
- `"investigation"` — Mystery/investigation
- `"rift"` — Planar rift-related
- `"dungeon"` — Dungeon delve
- `"major"` — Major story arc
- `"inter-guild"` — Multi-faction
- `"high-stakes"` — High consequences
- `"epic"` — Epic-level adventure
- `"divine"` — Divine intervention involved
- `"tower"` — Tower of Last Chance specific

## Mission Type Enum

- `"standard"` — Regular mission
- `"dungeon-delve"` — Multi-room dungeon
- `"investigation"` — Mystery/investigation
- `"combat"` — Combat-focused
- `"social"` — Roleplay-focused
- `"heist"` — Heist/infiltration

## Encounter Type Enum

- `"combat"` — Combat encounter
- `"social"` — Social/roleplay encounter
- `"exploration"` — Exploration/discovery
- `"trap"` — Trap or hazard
- `"skill_challenge"` — Skill challenge

## Image Type Enum

- `"battle_map"` — VTT-ready battle map
- `"location"` — Location/scene illustration
- `"creature"` — Creature/monster art
- `"npc_portrait"` — NPC portrait
- `"item"` — Item illustration
- `"map_tile"` — Individual map tile (dungeon delve)

## Examples

### Standard Mission

```json
{
  "metadata": {
    "id": "mission_abc123",
    "title": "The Silent Vault",
    "faction": "Glass Sigil",
    "tier": "high-stakes",
    "mission_type": "standard",
    "cr": 9,
    "party_level": 8,
    "player_name": "Party of Shadows",
    "player_count": 4,
    "runtime_minutes": 180,
    "reward": "2000 EC + faction favor",
    "generated_at": "2026-04-02T14:30:00Z",
    "version": "1.0"
  },
  "content": {
    "overview": "Glass Sigil has discovered rumors of a hidden vault beneath the merchant quarter...",
    "briefing": "You are summoned to the Glass Sigil's headquarters...",
    "act_1": "The party meets with Grandmaster Vex...",
    "act_2": "Investigation leads to the vault's location...",
    "act_3": "Final confrontation with vault guardians...",
    "rewards_summary": "Upon success, Glass Sigil owes the party a significant favor..."
  },
  "encounters": [
    {
      "id": "enc_0",
      "name": "Vault Guardians",
      "type": "combat",
      "difficulty": "hard",
      "location": "Grand Vault Chamber",
      "description": "Three enchanted constructs guard the vault entrance",
      "creatures": [
        {
          "name": "Iron Golem",
          "cr": 7,
          "hp": 165,
          "ac": 17,
          "count": 1
        }
      ],
      "party_xp": 1800
    }
  ],
  "npcs": [
    {
      "id": "npc_0",
      "name": "Grandmaster Vex",
      "title": "Leader of Glass Sigil",
      "location": "Glass Sigil Headquarters",
      "role": "quest_giver",
      "faction": "Glass Sigil",
      "description": "A stern woman with silver eyes and intricate tattoos",
      "personality": ["pragmatic", "cautious", "intelligent"],
      "goals": ["Recover the Vault's contents", "Maintain Glass Sigil's secrecy"],
      "quotes": ["The vault's location has been lost for centuries.", "We need trustworthy allies for this task."]
    }
  ],
  "images": [
    {
      "id": "img_0",
      "filename": "images/vault_chamber.png",
      "type": "battle_map",
      "title": "Grand Vault Chamber",
      "associated_encounter": "enc_0"
    }
  ]
}
```

### Dungeon Delve

```json
{
  "metadata": {
    "id": "mission_del123",
    "title": "Dungeon Delve: Forgotten Catacombs",
    "faction": "Independent",
    "tier": "dungeon",
    "mission_type": "dungeon-delve",
    "cr": 6,
    "party_level": 5,
    "runtime_minutes": 180,
    "reward": "500 EC + 100 Kharma",
    "generated_at": "2026-04-02T15:00:00Z",
    "version": "1.0"
  },
  "content": {
    "overview": "The Forgotten Catacombs lie beneath the Eastern Warrens...",
    "act_1": "Room descriptions begin here...",
    "act_5": "Upon clearing the dungeon..."
  },
  "dungeon_delve": {
    "layout_name": "5-room Dungeon",
    "aesthetic": "gothic",
    "total_rooms": 5,
    "entrance_room_id": "room_01",
    "boss_room_id": "room_05",
    "rooms": [
      {
        "id": "room_01",
        "number": 1,
        "name": "Entrance Hall",
        "type": "entrance",
        "description": "You descend worn stone stairs into darkness...",
        "features": ["collapsed pillars", "scattered bones"],
        "exits": {
          "east": "room_02"
        }
      },
      {
        "id": "room_05",
        "number": 5,
        "name": "Lich's Chamber",
        "type": "boss",
        "description": "A powerful undead lich awaits...",
        "encounter": {
          "id": "enc_boss",
          "name": "The Lich",
          "type": "combat",
          "creatures": [
            {
              "name": "Lich",
              "cr": 11,
              "hp": 135
            }
          ]
        }
      }
    ]
  },
  "images": [
    {
      "id": "img_map",
      "filename": "composite_map.png",
      "type": "battle_map",
      "title": "Forgotten Catacombs Map"
    },
    {
      "id": "img_tile_01",
      "filename": "tiles/room_01.png",
      "type": "map_tile",
      "title": "Room 1: Entrance"
    }
  ]
}
```

## Usage with Python

```python
from src.mission_builder.mission_json_builder import create_mission_module

# Create a mission
builder = create_mission_module(
    title="The Silent Vault",
    faction="Glass Sigil",
    tier="high-stakes",
    cr=9,
    party_level=8,
)

# Add content
builder.add_overview("Glass Sigil has discovered...") \
       .add_acts(act_1="...", act_2="...") \
       .add_npc("Grandmaster Vex", role="quest_giver", faction="Glass Sigil") \
       .add_encounter("Vault Guardians", "combat", difficulty="hard") \
       .add_image("images/vault_chamber.png", "battle_map", title="Grand Vault Chamber")

# Build and save
module = builder.build(validate=True)
output_path = builder.save_json(Path("generated_modules/mission_abc123"))
```

## Validation

Validation checks:
- ✅ All required fields present
- ✅ Metadata has title, faction, tier, mission_type, cr, party_level
- ✅ Content has overview
- ✅ Encounters have name and type
- ✅ NPCs have name
- ✅ Images have filename and type
- ✅ Dungeon delves have rooms if mission_type is "dungeon-delve"

```python
from src.mission_builder.schemas import validate_mission_module

is_valid, errors = validate_mission_module(module)
if not is_valid:
    for error in errors:
        print(f"Error: {error}")
```

## Migration from DOCX

The schema includes backward-compatibility `sections` for tools that still expect DOCX-style content:

```json
{
  "sections": {
    "overview": "...",
    "acts_1_2": "...",
    "acts_3_4": "...",
    "act_5_rewards": "..."
  }
}
```

This allows the same JSON to be processed by both modern tools and legacy DOCX builders.

## Future Extensions

Possible future additions:
- Quest hooks and flags
- Faction reputation changes
- Loot generation by rarity
- Trap mechanics and save DCs
- Skill challenge mechanics
- VTT-specific metadata (Roll20, Foundry)
- Character advancement tracking
