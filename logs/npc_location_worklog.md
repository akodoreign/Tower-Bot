# NPC Location & Underground Population Worklog
**Started:** 2026-03-27
**Status:** IN PROGRESS

## Phase 1: Gazetteer Underground Expansion ✅ COMPLETE
Created `city_gazetteer.json` with:
- Ring structure (0-5)
- All districts with sub_areas
- Underground network:
  - **Sewers**: 7 major sections (Forum, Sanctum, Market, Residential, Industrial, Grid 7, Deep)
  - **Lairs**: 8 creature lairs (Rat King's Warren, Slime Pits, Spider Galleries, Goblin Warrens, Carrion Caves, Troll Depths, Wyvern Roost, Mimic Alley)
  - **Dungeons**: 8 dungeon complexes (Old Prison, Sunken Temple, Artificer's Folly, Merchant Vaults, Warden Tombs, Rift Laboratories, Drowned Coliseum, Thane's Labyrinth)
  - **Sanctums**: 10 faction sanctums (Choir Undercroft, Thane's Inner Sanctum, Widow's Web, Memory Vault, Saints' Refuge, Forge Shrine, Counting House, Arena Crypts, Silent Library, Tower's Roots)
  - **Special**: Echo Alley, Fungal Forest, Crystalline Caves, Bone Market, Drowning Pools, Rift Scar Zones

---

## Phase 2: NPC Location Updates
### Methodology:
- Group NPCs by faction
- Assign locations based on: faction territory, species preferences, role, and personality
- Underground races (kobolds, goblins) get sewer/warren locations when appropriate
- Cultists get Collapsed Plaza / cult areas
- Archivists get Archive Row / library areas
- Wardens get Outer Wall / military areas
- etc.

### NPCs to Update (those with vague/missing locations):

#### BATCH 1: Brother Thane's Cult Members
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Gorgon Gizzick | "Beneath the Dome's Shadow" (vague) | PENDING | Goblin cult speaker |
| Zara Forgemender | "The Forge District, Brother Thane's Cathedral" | PENDING | Warforged blacksmith |
| Arthur Fyreclaw | "The Pit, Brother Thane's Sanctum" | PENDING | Interrogator |
| Seraphina Luminara | "The Sunken Quarters, Brother Thane's Sanctum" | PENDING | Healer |
| Thalia Ignis-Veil | "The Infernal Spire" | PENDING | Fire ritualist |
| Edwyn Shadowmantle | "The Spire of Shadows" (vague) | PENDING | Scribe |
| Torinn Wyrmbane | "The Inner Sanctum" | PENDING | Ritual leader |
| Zelos Firetongue | "The Heart of Ash" | PENDING | Purification leader |
| Seraphina Nightshade-Ironheart | "Lower Depths, Catacombs" | PENDING | Speaker |
| Ghurrag Ironmace | "Squalor's Gulch" (vague) | PENDING | Orc speaker |

#### BATCH 2: Glass Sigil / Guild of Ashen Scrolls
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Thrain Stonefist | "The Archive Quarter, Scroll Vault" | OK - keep | Good fit |
| Elara Starbinder | "The Scholar's Quarter, Glass Sigil Library" | OK - keep | Good fit |
| Kyrus Fireeye | "Catacombs, Glass Sigil Archive" | OK - needs refine | Tiefling, underground preference |
| Arion Celestia | "Hallowed Archive, Inner Sanctum" | PENDING | Secretly cult |
| Nalus Thundertide | "Scriptorium" | OK - keep | Senior role |
| Seraph Zephyrion | "South Spire, Archive of Forgotten Histories" | OK - keep | Junior role |

#### BATCH 3: Wardens of Ash  
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Gruum Boneshaper | "The Forge — the heart of the Warden's district" | PENDING | Dwarf blacksmith |
| Kyra Noxfire | "The Forge, the heart of the Warden's district" | PENDING | Tiefling frontline |
| Zephyrus Sylphim | "The Ashen Hollow" | PENDING | Genasi sergeant |
| Arin Obsidianwhisper | "The Ash Wastes" | PENDING | Human sentry |
| Grothor Grimclaw | "The Cryptwards" (wrong - that's Argent territory) | PENDING | Orc, defected to Wardens |
| Elysia Thornshadow | "The Forge District, Wardens' barracks" | OK - refine | Half-elf sergeant |
| Eolande Starfall | "The Inferno's Embrace" | PENDING | Elf sergeant |
| Gurrek Ironheart | "The Mudflats district" | PENDING | Orc recruit |
| Voris Ironhammer | "Tower's Edge, the Wardens' barracks" | PENDING | Now Guild of Ashen Scrolls |

#### BATCH 4: Argent Blades
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Groz Krax | "The Spire district, Argent Blades headquarters" | PENDING | Half-orc senior |
| Grom Vulgarn | "Gravel District, Argent Blades HQ" | PENDING | Half-orc senior |
| Eamon Hawthorne | "Mourning Quarter, Argent Blades' Fortress" | PENDING | Human blade |
| Thoren Grudbreaker | "The Ironclad district" | PENDING | Half-orc prospect |
| Elara Celestian | "Argent Quarter, Argent Blade's Sanctum" | PENDING | Aasimar prospect |
| Elias Whisperstep | "Southspire, Argent Blades' Headquarters" | PENDING | Tabaxi blade |
| Cassius Argent-Heart | "The Slaughterhouse District" | PENDING | Human senior |

#### BATCH 5: Serpent Choir
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Snake-Eyes Snigar | "The Narrows, Slithering Serpent's Tavern" | OK - keep | Goblin in tavern works |
| Kyri Zaltazar | "Sewers of the Cinder's Heart district" | PENDING | Kobold - needs sewer detail |
| Thyra Scalescar | "The Pit" | PENDING | Dragonborn enforcer |

#### BATCH 6: Obsidian Lotus
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Eira Shadowstalk | "The Shattered Quarter" | PENDING | Tabaxi ghost |
| Lysandra Stardust | "The Mists" | PENDING | Aasimar ghost |
| Grimwit Stone-Eye | "The Tarnished Spire, Lower Undercity" | PENDING | Gnome specialist |

#### BATCH 7: Iron Fang Consortium
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Elara Ironclaw | "The Shattered Spire" | PENDING | Elf street runner |
| Tilda Ironheart | "Lower Dockyards, Rust Alley" | OK - keep | Human runner |
| Giselle Ironwhisper | "The Ironspire district" | PENDING | Human runner |
| Gavrik Ironshield | "The Forge, a bustling market district" | PENDING | Warforged runner |
| Kyrus Ironscale | "Iron Fang Consortium headquarters" | OK - keep | Dragonborn agent |

#### BATCH 8: Patchwork Saints
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Gromm Ironhand | "The Forge District, at the heart of the Patchwork Saints' headquarters" | PENDING | Half-orc saint |
| Kip Stonefang | "The Winding Ward, Patchwork Saints' Headquarters" | PENDING | Kobold saint |
| Grimbush Gizzlethorn | "The Patchwork District" | PENDING | Goblin volunteer |
| Thalia Elenshade | "Silk Alley, The Worn district" | OK - keep | Half-elf saint |
| Lysander Elveshadow | "The Mottled Quarter" | PENDING | Half-elf volunteer |

#### BATCH 9: Tower Authority / FTA
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Thrastus Flameheart | "The Citadel" | PENDING | Dragonborn senior |
| Klara Lodestone | "Downtower District" | PENDING | Gnome officer |
| Zara Leafwhisper | "Lantern's Reach, Upper Spire" | OK - keep | Tabaxi intern |
| Zippy Quickclaw | "The Upper Spire, Compliance Bureau" | PENDING | Kobold intern |
| Giselle Ironhammer | "Sub-Level 5, Tower Authority Enforcement District" | OK - keep | Warforged officer |
| Isabelle Hartling | "The Upper Spire, Compliance Office" | OK - keep | Human intern |
| Gideon Steelforge | "The Tower of Last Chance, Command Center" | OK - keep | Warforged senior |
| Rianna Elenshade-Ironhammer | "The Spire's Watch" | OK - keep | Half-elf intern |

#### BATCH 10: Adventurers Guild
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Nimue Silverpaw | "Lower Ward, The Ragged Alley" | PENDING | Tabaxi E-rank |
| Sebastian Azrael | "The Pit" | PENDING | Tiefling F-rank |
| Thoren Azurescale | "The Razor's Edge district" | PENDING | Dragonborn F-rank |
| Seraphina Nightwatch | "The Rivet district" | OK - keep | Aasimar E-rank |

#### BATCH 11: Independent
| NPC | Current Location | New Location | Reasoning |
|-----|-----------------|--------------|-----------|
| Gurthok Ironhide | "The Midden — Lower Undercity" | OK - keep | Orc mercenary |
| Zinnia Snakefang | "Crimson Alley" | OK - keep | Kobold scavenger |
| Gruggar Grimshackle | "The Rotting Quarter, Black Market" | PENDING | Orc smuggler |

---

## Progress Tracker
- [x] Phase 1: Gazetteer creation
- [ ] Phase 2: NPC updates
  - [ ] Batch 1: Brother Thane's Cult (10 NPCs)
  - [ ] Batch 2: Glass Sigil (6 NPCs) 
  - [ ] Batch 3: Wardens of Ash (9 NPCs)
  - [ ] Batch 4: Argent Blades (7 NPCs)
  - [ ] Batch 5: Serpent Choir (3 NPCs)
  - [ ] Batch 6: Obsidian Lotus (3 NPCs)
  - [ ] Batch 7: Iron Fang Consortium (5 NPCs)
  - [ ] Batch 8: Patchwork Saints (5 NPCs)
  - [ ] Batch 9: Tower Authority (8 NPCs)
  - [ ] Batch 10: Adventurers Guild (4 NPCs)
  - [ ] Batch 11: Independent (3 NPCs)

---

## Location Reference (from gazetteer)

### Brother Thane's Cult Territory:
- Collapsed Plaza, Cult House (main gathering)
- Collapsed Plaza Depths → Thane's Inner Sanctum
- Collapsed Plaza Depths → Cult Catacombs
- Collapsed Plaza Depths → Thane's Labyrinth (under construction)
- Cult Corners, Brother Thane's Meeting Hall (Ring 2, public)

### Argent Blades Territory:
- Guild Spires, Gilded Halls (headquarters)
- Arena Crypts (initiation sanctum)

### Wardens of Ash Territory:
- Outer Wall (all gates and bastions)
- Wall Tunnels (patrol routes, armories)
- Forge Shrine (Southern Warrens - hidden)

### Glass Sigil Territory:
- Archive Row (Grand Archive Dome, Scroll Vault)
- Archive Catacombs (Forbidden Stacks, Memory Vault)

### Serpent Choir Territory:
- Sanctum Quarter (Pantheon Walk, Choir Hall)
- Sanctum Catacombs (Burial Vaults, Choir Undercroft)

### Obsidian Lotus Territory:
- Eastern Warrens (The Widow's Web - HQ)
- Neon Row back rooms
- Echo Alley

### Iron Fang Consortium Territory:
- Markets Infinite (Crimson Alley, Relic Row)
- Ironworks (factories, shipping)
- Consortium Underhalls (The Counting House)

### Patchwork Saints Territory:
- Scrapworks (Mara's territory)
- Shantytown Heights (Stack Housing, Saints' Refuge)
- Eastern Warrens (Saints' Haven)

### Underground Special:
- Sewers (7 sections)
- Goblin Warrens (Northern Warrens) - good for goblins
- Fungal Forest (Northern Warrens) - myconids, deep dwellers
- Bone Market (Underbelly Warrens) - black market
