# Skill: VTT Battlemap Generation
**Keywords:** map, battlemap, VTT, tactical, grid, combat, dungeon, location, terrain
**Category:** generation
**Version:** 1
**Source:** seed

## Purpose
This skill governs how the bot generates VTT-compatible battlemaps for D&D 5e 2024 mission modules. Maps are generated automatically as part of the mission module pipeline using A1111/Stable Diffusion.

---

## MAP QUALITY STANDARDS

### Visual Requirements
- **Top-down orthographic view** — no perspective, no angle
- **Clear boundaries** — walls, edges, and terrain features clearly defined
- **High contrast** — features distinguishable for tactical play
- **Grid-ready** — 1024x1024px works well with standard VTT grids
- **No characters/tokens** — maps should be empty for DM to place tokens

### Undercity Aesthetic
All maps should feel like they belong in the dark urban fantasy Undercity:
- Dim, atmospheric lighting (not bright daylight)
- Industrial/fantasy hybrid elements (pipes, magic crystals, stone, metal)
- Signs of wear, age, and use
- Dark color palette with accent lighting (torches, magic glow, bioluminescence)

---

## DISTRICT-SPECIFIC STYLES

Each district has a distinct visual identity:

### Markets Infinite
- Cobblestone streets, worn smooth
- Market stalls, crates, barrels
- Hanging awnings and canvas covers
- Lantern light casting warm pools
- Cramped alleyways between stalls

### The Warrens
- Ruined and collapsed structures
- Debris piles, rubble, broken furniture
- Makeshift repairs and shelters
- Exposed pipes and infrastructure
- Dangerous terrain (holes, unstable floors)
- Dim, unreliable lighting

### Guild Spires
- Polished stone floors
- Ornate pillars and architecture
- Guild banners and emblems
- Clean lines, organized spaces
- Magic lighting (floating orbs, glowing runes)

### Sanctum Quarter
- Temple architecture
- Religious symbols and iconography
- Altar spaces and ceremonial areas
- Incense braziers, candles
- Divine light effects

### Grand Forum
- Open plaza spaces
- Fountains and water features
- Statue pedestals
- Wide streets and public squares
- Civic architecture

### Outer Wall
- Fortifications and battlements
- Guard towers and watchtowers
- Heavy stone construction
- Murder holes and defensive positions
- Patrol routes and gatehouse areas

### Underground/Sewers
- Rough cave walls or brick tunnels
- Water channels and walkways
- Stalactites/pipes overhead
- Damp stone, moss
- Dim bioluminescence or torch sconces

---

## SCENE TYPE FEATURES

Different scene types need different tactical elements:

### Boss/Lair Encounters
- Large central open area for boss movement
- Dramatic centerpiece (throne, altar, machine)
- Environmental hazards (fire, acid, magic)
- Multiple elevation levels
- Escape routes (for players who are losing)

### Standard Combat
- Clear cover positions (half and full)
- Chokepoints for tactical play
- At least 3 distinct terrain features
- Room for flanking maneuvers
- Objects that can be interacted with

### Investigation Scenes
- Lots of searchable clutter
- Hiding spots (for enemies or evidence)
- Multiple entry/exit points
- Details that tell a story
- Evidence markers (blood, footprints, etc.)

### Ambush Sites
- Concealment positions for ambushers
- High ground advantages
- Shadow areas
- Limited visibility lines
- Trap placement opportunities

### Chase Sequences
- Long corridors or paths
- Obstacles to vault/navigate
- Multiple route options
- Dead ends and shortcuts
- Environmental hazards to avoid

---

## PROMPT ENGINEERING

### Base Style (always include)
```
top-down tactical battlemap, D&D VTT map, grid-ready, 
dungeon map style, dark fantasy, high contrast, clear edges, 
flat lighting from above, no perspective distortion, orthographic view,
detailed floor textures, clear walls and boundaries
```

### Negative Prompt (always include)
```
3d render, perspective, isometric, character, people, monsters,
side view, angle, sky, clouds, sun, horizon, blurry, low quality,
realistic photo, photograph, watermark, signature, text, UI elements,
miniatures, tokens, grid overlay, numbers, letters
```

### Building Effective Prompts
1. Start with base style
2. Add specific location description
3. Add district aesthetic keywords
4. Add scene type tactical features
5. Add 2-3 specific visual elements from the scene description

### Example Prompt
```
top-down tactical battlemap, D&D VTT map, grid-ready, dungeon map style,
dark fantasy, high contrast, orthographic view,
location: collapsed warehouse in the Warrens,
ruined buildings, debris piles, broken furniture, exposed pipes,
cover objects, chokepoints, environmental hazards,
wooden crates, fallen beams, flickering torchlight
```

---

## ITERATIVE IMPROVEMENT

The image_ref.py system enables maps to improve over time:

### How References Work
1. First map of a location → txt2img (no reference)
2. Map saved as reference: `image_refs/locations/[slug]/ref_001.png`
3. Next map of same location → img2img with denoise=0.50
4. Result builds on previous, more consistent
5. New map replaces ref_001, old becomes ref_002 (keeps 3 max)

### Pinned References
DM can pin a particularly good map as the canonical reference:
- Stored as `pinned.png` in the location directory
- Always used instead of rotating refs
- Never deleted by rotation

### Denoising Strength
- 0.50 for locations (moderate freedom, keeps layout)
- 0.45 for NPCs (preserve face/identity)
- 0.55 for scenes (more freedom, composition varies)

---

## COMMON FAILURES TO AVOID

1. **Perspective/angle** — Maps must be pure top-down
2. **Characters in frame** — Maps should be empty
3. **Too dark/muddy** — Features must be distinguishable
4. **Grid overlay** — Let VTT add the grid
5. **Text/labels** — No text in the image
6. **Wrong scale** — Buildings too small/large for tactical play
7. **Inconsistent style** — All maps should feel like the same world

---

## INTEGRATION

Maps are generated automatically when `generate_module()` runs:
1. DOCX is created
2. `generate_module_maps()` called
3. Scenes extracted from module content
4. Maps generated for each scene (max 4)
5. Maps saved to `generated_modules/[module]/maps/`
6. Posted to Discord with the module

The system is non-blocking — if A1111 is unavailable, module still generates without maps.
