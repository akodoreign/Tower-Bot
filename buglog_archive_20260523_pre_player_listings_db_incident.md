# Mission Pipeline Quality Report

**Generated:** 2026-05-21  
**Previous buglog archived:** `buglog_archive_20260521_170300_pre_pipeline_quality.md`  
**Scope:** Read-only grading of mission module builders for quality, diversity/replay value, and table playability from source plus generated module HTML where available. No source files were changed.

## Pipeline Count Clarification

There are currently **34 board mission types** in `mission_type_templates`. Those are the posting categories the mission board can show, such as Bounty Hunt, Courier / Delivery, Patrol Contract, Rift Clearance, Smuggling Run, and so on.

There are **22 `*_pipeline.py` files** in `src/mission_builder`, but two of those are special cases:

- `novel_pipeline.py` is legacy/prep-lore style and can be ignored for table module grading.
- `published_pipeline.py` is not a board type. It is the default table-first fallback builder used when a mission type does not have a specialized standalone pipeline.

That leaves **20 specialized type-specific module pipelines** currently routed in `src/mission_builder/__init__.py`. The remaining board mission types are either routed into one of those specialized pipelines by aliases, handled by `published_pipeline.py`, or still low-weight/unbuilt on the board side.

## Board Type Coverage Matrix

This is the important distinction: the board has more mission **types** than the module builder has dedicated **pipeline files**. Some board types intentionally collapse into a nearby specialized builder.

| Board Mission Type | Current Module Builder | Coverage |
|---|---|---|
| Ambush | `ambush_pipeline.py` | Dedicated |
| Assassination | `assassination_pipeline.py` | Dedicated but board-weighted low |
| Assault | `assault_pipeline.py` | Dedicated |
| Battle | `battle_pipeline.py` | Dedicated but board-weighted low |
| Bounty Hunt | `published_pipeline.py` fallback | No dedicated module pipeline |
| Courier / Delivery | `escort_pipeline.py` by `deliver`/`transport` keywords | Alias coverage |
| Defense | `defense_pipeline.py` | Dedicated |
| Discovery | `discovery_pipeline.py` | Dedicated |
| Dungeon Delve | `infestation_pipeline.py` by `dungeon`/`delve` keywords | Alias coverage |
| Epic / Divine Mission | `published_pipeline.py` fallback | No dedicated module pipeline |
| Escort Mission | `escort_pipeline.py` | Dedicated |
| Exploration | `exploration_pipeline.py` | Dedicated |
| Faction Espionage | `published_pipeline.py` fallback | No dedicated module pipeline; should likely map to Infiltration |
| First Contact | `first_contact_pipeline.py` | Dedicated |
| Gathering | `gather_pipeline.py` | Dedicated |
| Heist | `heist_pipeline.py` | Dedicated |
| High-Stakes Contract | `published_pipeline.py` fallback | No dedicated module pipeline; may need routing to Assassination/Recovery/Political |
| Infestation | `infestation_pipeline.py` | Dedicated |
| Infiltration | `infiltration_pipeline.py` | Dedicated |
| Inter-Guild Conflict | `published_pipeline.py` fallback | No dedicated module pipeline; may need routing to Negotiation/Sabotage/Infiltration |
| Investigation | `investigation_pipeline.py` | Dedicated |
| Negotiation | `negotiation_pipeline.py` | Dedicated |
| Neighbourhood Job | `published_pipeline.py` fallback | No dedicated module pipeline |
| Patrol Contract | `published_pipeline.py` fallback | No dedicated module pipeline |
| Political Intrigue | `published_pipeline.py` fallback | No dedicated module pipeline |
| Protection Detail | `escort_pipeline.py` by `protect` keyword | Alias coverage |
| Puzzle | `puzzle_pipeline.py` | Dedicated |
| Recovery | `recovery_pipeline.py` | Dedicated |
| Rescue Operation | `rescue_pipeline.py` | Dedicated |
| Rift Clearance | `published_pipeline.py` fallback | No dedicated module pipeline; should likely map to Exploration/Infestation/Discovery depending on prompt |
| Sabotage | `sabotage_pipeline.py` | Dedicated |
| Smuggling Run | `published_pipeline.py` fallback | No dedicated module pipeline; should likely map to Heist/Escort |
| Strange Occurrences | `strange_occurrences_pipeline.py` | Dedicated |
| Theft / Heist | `heist_pipeline.py` by `theft` keyword | Alias coverage |

**Coverage totals:**

- 20 board types have direct dedicated pipeline coverage.
- 4 board types have alias coverage through a nearby dedicated pipeline: Courier / Delivery, Dungeon Delve, Protection Detail, Theft / Heist.
- 10 board types currently fall to `published_pipeline.py`: Bounty Hunt, Epic / Divine Mission, Faction Espionage, High-Stakes Contract, Inter-Guild Conflict, Neighbourhood Job, Patrol Contract, Political Intrigue, Rift Clearance, Smuggling Run.

**Board weighting mismatch:** `mission_board.py` still treats `Battle` and `Assassination` as low-weight/unbuilt even though both now have routed standalone pipelines. That should be corrected if those builders are considered active.

## Rubric

- **Quality:** coherence, specificity, DB/API grounding, useful DM-facing content, and internal consistency.
- **Diversity:** replay variation across factions, locations, stakes, objectives, complications, and outcomes.
- **Playability:** whether the generated HTML can be run at the table with minimal extra prep: scenes, checks, maps, clocks, handouts, stat blocks, session tools, and clear success/failure states.

Scores are 1-10. A 7 is usable with light prep. An 8+ is close to table-ready. A 5-6 is a scaffold that still asks the DM to invent important parts.

## Actual Multi-Run Bakeoff

**Run:** `generated_modules\pipeline_bakeoff_20260521_172813\pipeline_bakeoff_report.md`  
**Harness:** `scripts\pipeline_bakeoff.py --runs 2`  
**Scope:** 20 dedicated routed pipelines, 2 generated modules each, maps enabled through the downloaded/library map path, Mimir disabled, OpenAI disabled.

The bakeoff completed 38 successful generated modules out of 40 attempts. The two failures were both Assassination. Map artifacts were included in scoring: image count, VTT sidecar count, `maps.html`, and whether the module linked the map page.

Important caveat: the current harness diversity metric returned `0.0` for every successful pipeline, which is not credible given the visible changes in word counts, map selections, and generated details. Treat the uniqueness column in the generated report as a harness bug / insufficient metric, not as proof that every pipeline is identical. Diversity still needs human review plus a better artifact comparison pass.

| Pipeline | Runs OK | Avg Score | Map Delivery | Bakeoff Verdict |
|---|---:|---:|---|---|
| Ambush | 2/2 | 10.0 | Good: image, VTT, `maps.html`, linked | Very runnable; one run leaked `None` in faction/interference text. |
| Assassination | 0/2 | 0.0 | None | Broken builder. Reproduced crash in `_clean_json()` before module completion. |
| Assault | 2/2 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong table module. |
| Battle | 2/2 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong in bakeoff, despite older source-review concerns about board weighting and repetition. |
| Defense | 2/2 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong table module. |
| Discovery | 2/2 | 5.4 | No maps copied | Weakest successful module: repeated `Test 1-5` placeholders and thin playable content. |
| Escort | 2/2 | 9.4 | Good enough: 2 images, 1 VTT, `maps.html`, linked | Much better with library maps; still low on route/procedure controls. |
| Exploration | 2/2 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong table module. |
| First Contact | 2/2 | 7.2 | No maps copied | Usable social kit, but should still get a contact-site/meeting-place map when appropriate. |
| Gathering | 2/2 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong table module. |
| Heist | 2/2 | 9.8 | Good: image, VTT, `maps.html`, linked | Strong; minor `None` leakage remains. |
| Infestation | 2/2 | 6.8 | Partial: images and `maps.html`, no VTT sidecars | Playable room crawl, but no forms/check controls and monster text can render as `None -- signs of recent passage only.` |
| Infiltration | 2/2 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong in bakeoff; both runs selected the same map, so map diversity/memory needs review. |
| Investigation | 2/2 | 8.8 | No maps copied | Strong case module; map absence may be fine if scenes are social/evidence-based, but location boards could help. |
| Negotiation | 2/2 | 7.4 | No maps copied | Usable, but both runs logged "Plan too generic - using fallback"; social location context needs stronger generation. |
| Puzzle | 2/2 | 8.8 | No maps copied | Strong structure, but visual/puzzle handouts or diagrams should replace blank map delivery. |
| Recovery | 2/2 | 7.6 | No maps copied | Usable but still fallback-heavy; placeholder leakage detected. |
| Rescue | 2/2 | 9.9 | Good: image, VTT, `maps.html`, linked | Strong table module. |
| Sabotage | 2/2 | 9.4 | Good: image, VTT, `maps.html`, linked | Better than source-only review expected; minor `None` leakage remains. |
| Strange Occurrences | 2/2 | 8.8 | No maps copied | Good case/weird-event module; should produce or choose incident/location visuals when the event is spatial. |

### Confirmed Bakeoff Bugs

1. **Assassination pipeline hard-crash was observed, then superseded by current source.**  
   The earlier 2-run harness reproduced a bad `_clean_json()` regex crash. Current source no longer has that exact regex, and the later 5-run batch passed 5/5. Treat this as historical unless it reappears in live logs.

2. **Discovery emits obvious placeholder test labels.**  
   Both Discovery runs generated `Test 1` through `Test 5` style identification checks. This is not just "low flavor"; it is visible table-facing placeholder content.

3. **Infestation map packaging is inconsistent.**  
   Both Infestation runs linked `maps.html` and included images, but scored zero VTT sidecars. The module can say a battle map exists while VTT delivery is incomplete.

4. **Infestation can leak `None` as encounter text.**  
   Both Infestation runs contained monster blocks like `None -- signs of recent passage only.` That is table-facing broken content.

5. **Negotiation validation is falling back too often.**  
   Both bakeoff runs logged `Plan too generic - using fallback`. The output is playable, but the pipeline is not reliably producing a specific plan from its own context.

6. **The bakeoff diversity scorer is broken or too weak.**  
   The generated report assigned `0.0` uniqueness to every successful pipeline. This should be fixed before using automated diversity scores for decisions.

## Fresh 2x Playability Pass

**Run:** `generated_modules\pipeline_bakeoff_20260522_050932\pipeline_bakeoff_report.md`  
**Generated:** 2026-05-22 05:33:13  
**Scope:** all 20 routed specialized pipelines, 2 generated modules each, maps enabled.  
**Result:** 40/40 module attempts succeeded.

This pass is scored strictly as table playability: whether the generated HTML has enough structure, session controls, checks, maps/handouts where expected, and clean enough text to run with minimal extra prep.

| Pipeline | Runs OK | Playability Avg | Playability Band | Notes |
|---|---:|---:|---|---|
| Ambush | 2/2 | 10.0 | Excellent | Clean; strong map/session delivery. |
| Assassination | 2/2 | 9.9 | Excellent | Clean; target routine and map support are run-ready. |
| Assault | 2/2 | 10.0 | Excellent | Clean; very strong table controls and battle structure. |
| Battle | 2/2 | 10.0 | Excellent | Clean; large-fight structure is runnable. |
| Defense | 2/2 | 10.0 | Excellent | Clean; strong waves, morale, and map support. |
| Discovery | 2/2 | 7.4 | Usable | Improved from prior placeholder-heavy pass, but no maps copied and still thin. |
| Escort | 2/2 | 9.4 | Strong | Clean; route/target support is playable with maps. |
| Exploration | 2/2 | 10.0 | Excellent | Clean; strong survey structure and map support. |
| First Contact | 2/2 | 7.2 | Usable | No maps copied; needs stronger staged encounter play. |
| Gathering | 2/2 | 10.0 | Excellent | Clean; strong logistics and session tracker. |
| Heist | 2/2 | 9.8 | Strong | Very playable, but both runs had `None` leakage. |
| Infestation | 2/2 | 8.0 | Strong | Map delivery works; still has few checkbox/form controls compared with top pipelines. |
| Infiltration | 2/2 | 10.0 | Excellent | Clean; strong scene and map support. |
| Investigation | 2/2 | 8.2 | Strong | Strong case tools, but one run leaked `None`; no maps copied. |
| Negotiation | 2/2 | 7.4 | Usable | No maps copied; one run used generic-plan fallback. |
| Puzzle | 2/2 | 8.8 | Strong | Good mechanics; no maps/visual handouts copied. |
| Recovery | 2/2 | 7.8 | Usable | Playable but had placeholder/None leakage and no maps. |
| Rescue | 2/2 | 8.0 | Strong | Both runs were aftermath/cleanup rescues with no maps; playable but less tactical. |
| Sabotage | 2/2 | 9.4 | Strong | Playable with maps; `None` leakage remains. |
| Strange Occurrences | 2/2 | 8.8 | Strong | Stable case/weird-event play; no maps copied. |

**Current playability ranking:**

- **Excellent:** Ambush, Assassination, Assault, Battle, Defense, Exploration, Gathering, Infiltration.
- **Strong:** Escort, Heist, Infestation, Investigation, Puzzle, Rescue, Sabotage, Strange Occurrences.
- **Usable but needs work:** Discovery, First Contact, Negotiation, Recovery.
- **Failing:** none in this pass.

**Fresh issues from this pass:**

1. **No hard pipeline failures in 40 attempts.**  
   This is a good sign for stability: every routed specialized pipeline produced two modules.

2. **`None` leakage still affects playability.**  
   Heist, Investigation, Recovery, and Sabotage had table-facing `None`/placeholder leakage in the generated report.

3. **Social/case pipelines still under-deliver maps or visual aids.**  
   Discovery, First Contact, Investigation, Negotiation, Puzzle, Recovery, Rescue, and Strange Occurrences copied no maps in this 2x pass. Some of those can be valid no-map missions, but several would play better with a venue map, clue board, evidence handout, puzzle visual, or incident diagram.

4. **Negotiation still falls back to generic planning.**  
   One of two Negotiation runs logged `Plan too generic - using fallback`, keeping it in the usable tier instead of strong.

## Board/Fallback 2x Playability Pass

**Run:** `generated_modules\pipeline_bakeoff_20260522_053701\pipeline_bakeoff_report_rescored.md`  
**Generated:** 2026-05-22  
**Scope:** 14 board categories beyond the first 20 specialized labels, 2 generated modules each, maps enabled.  
**Result:** 28/28 generated modules were present and scored after fixing the harness analyzer.

Important note: the first report in this folder, `pipeline_bakeoff_report.md`, is invalid. The modules generated, but the scorer crashed on its own variable-width lookbehind regex and marked every run as failed. The rescored report is the one to trust.

| Board Type | Routed Builder | Runs OK | Playability Avg | Playability Band | Notes |
|---|---|---:|---:|---|---|
| Bounty Hunt | Published fallback | 2/2 | 9.3 | Strong | Table-first structure worked; minor `None` leakage. |
| Courier / Delivery | Escort alias | 2/2 | 9.4 | Strong | Routed to Escort; maps/VTT present and clean. |
| Dungeon Delve | Infestation alias | 2/2 | 9.9 | Excellent | Routed to Infestation; one run leaked `None`, but otherwise very playable. |
| Epic / Divine Mission | Published fallback | 2/2 | 9.3 | Strong | Table-first structure worked; minor `None` leakage. |
| Faction Espionage | Infiltration alias | 2/2 | 9.3 | Strong | Routed to Infiltration; maps/VTT present, minor `None` leakage. |
| High-Stakes Contract | Published fallback | 2/2 | 9.3 | Strong | Table-first fallback handled it well; minor `None` leakage. |
| Inter-Guild Conflict | Published fallback | 2/2 | 10.0 | Excellent | Clean and highly playable in this sample. |
| Neighbourhood Job | Published fallback | 2/2 | 9.3 | Strong | Table-first structure worked; minor `None` leakage. |
| Patrol Contract | Published fallback | 2/2 | 9.3 | Strong | Table-first structure worked; minor `None` leakage. |
| Political Intrigue | Published fallback | 2/2 | 9.3 | Strong | Table-first structure worked; minor `None` leakage. |
| Protection Detail | Escort alias | 2/2 | 9.4 | Strong | Routed to Escort; maps/VTT present and clean. |
| Rift Clearance | Published fallback | 2/2 | 9.3 | Strong | Table-first structure worked; minor `None` leakage. |
| Smuggling Run | Published fallback | 2/2 | 9.3 | Strong | Table-first structure worked; minor `None` leakage. |
| Theft / Heist | Heist alias | 2/2 | 9.8 | Strong | Routed to Heist; very playable, but `None` leakage remains. |

**Board/fallback findings:**

1. **There are 34 board categories in practice, not just 20 pipeline files.**  
   The first 20 tests covered dedicated routed labels. This pass covered the remaining 14 board categories and alias/fallback paths.

2. **Published fallback is currently strong for unhandled board types.**  
   Bounty, Epic, High-Stakes, Inter-Guild, Neighbourhood, Patrol, Political, Rift, and Smuggling all generated runnable table-first modules with scene dialogs, session runner, NPC cards, quality report, and map artifacts.

3. **Alias routing is working.**  
   Delivery and Protection routed to Escort; Dungeon Delve routed to Infestation; Espionage routed to Infiltration; Theft routed to Heist.

4. **Minor `None` leakage is still the common quality tax.**  
   Published fallback outputs often scored high but had one `None` hit. Theft/Heist had two `None` hits per run.

5. **The harness scorer bug is fixed.**  
   `scripts\pipeline_bakeoff.py` no longer uses the illegal variable-width lookbehind that caused false failure reports.

## Expanded Five-Run Bakeoff

**Runs:** 2026-05-21, split into four smaller batches of 5 pipelines each.  
**Scope:** all 20 dedicated routed pipelines, 5 generated modules per pipeline, maps enabled through the downloaded/library map path.  
**Reports:**

- `generated_modules\pipeline_bakeoff_20260521_190952\pipeline_bakeoff_report.md`
- `generated_modules\pipeline_bakeoff_20260521_193203\pipeline_bakeoff_report.md`
- `generated_modules\pipeline_bakeoff_20260521_195805\pipeline_bakeoff_report.md`
- `generated_modules\pipeline_bakeoff_20260521_201536\pipeline_bakeoff_report.md`

This expanded pass covered the full routed set: Ambush, Assassination, Assault, Battle, Defense, Discovery, Escort, Exploration, First Contact, Gathering, Heist, Infestation, Infiltration, Investigation, Negotiation, Puzzle, Recovery, Rescue, Sabotage, and Strange Occurrences.

| Pipeline | Runs OK | Avg Score | Map Delivery | Expanded Verdict |
|---|---:|---:|---|---|
| Ambush | 5/5 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong table runner, but logs show repeated `condition_name` DB schema errors on early runs. |
| Assassination | 5/5 | 9.9 | Good: image, VTT, `maps.html`, linked | Current source passed all 5; earlier regex crash appears fixed in current file. |
| Assault | 5/5 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong, but map selection repeatedly favored map #230. |
| Battle | 5/5 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong generated structure with varied map picks. |
| Defense | 5/5 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong generated structure with varied maps and location beats. |
| Discovery | 5/5 | 5.4 | No maps copied | Consistently weak: every run had placeholder-style `Test 1-5` checks and no map artifacts. |
| Escort | 5/5 | 9.4 | Good enough: 2 images, 1 VTT, `maps.html`, linked | Better than source review suggested; target variety was good across 5 runs. |
| Exploration | 5/5 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong, with varied maps. |
| First Contact | 5/5 | 7.2 | No maps copied | Stable but thin; needs contact-site visuals or stronger encounter staging. |
| Gathering | 5/5 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong, but map choice repeated #149 often. |
| Heist | 5/5 | 9.8 | Good: image, VTT, `maps.html`, linked | Strong, but map selection stuck on #230 for 4 of 5 runs and `None` leakage remains. |
| Infestation | 5/5 | 7.8 | Good in report: 2 images, 2 VTT, `maps.html`, linked | Improved over earlier sample, but logs still say complete with `0 maps`; room retry/stub fallback happens often. |
| Infiltration | 5/5 | 10.0 | Good: image, VTT, `maps.html`, linked | Strong; map diversity improved across the 5-run pass. |
| Investigation | 5/5 | 8.1 | No maps copied | Strong case tools, but 3 of 5 runs leaked `None` and no map/location board is produced. |
| Negotiation | 5/5 | 7.3 | No maps copied | Playable but modest; 1 red flag and no map/venue support. |
| Puzzle | 5/5 | 8.7 | No maps copied | Strong mechanics, but one run had placeholder/None leakage and visual puzzle handouts are still absent. |
| Recovery | 5/5 | 8.1 | No maps copied | Builds clean modules, but every run logged `Unknown column 'home_district' in 'where clause'`. |
| Rescue | 5/5 | 9.1 | Mixed: active runs got maps; aftermath runs did not | Good variety between active and aftermath modes; no red flags. |
| Sabotage | 5/5 | 9.5 | Good: image, VTT, `maps.html`, linked | Stronger than source review suggested, but `None` leakage remains. |
| Strange Occurrences | 5/5 | 8.8 | No maps copied | Stable and playable; still needs incident/location visuals when spatial. |

### Expanded Bakeoff Confirmed Issues

1. **Discovery remains the weakest successful dedicated pipeline.**  
   Five out of five runs scored 5.4, emitted 10 placeholder hits each, and produced no map artifacts. This is now confirmed across repeated samples.

2. **Recovery has a live DB schema mismatch.**  
   Five out of five Recovery runs logged `Database error: 1054 (42S22): Unknown column 'home_district' in 'where clause'`. The modules still build, but the pipeline is querying a column that is not in the current MySQL schema.

3. **Ambush has a live DB schema mismatch.**  
   Early Ambush runs logged `Database error: 1054 (42S22): Unknown column 'condition_name' in 'field list'`. The modules still build, but the DB/API contract is stale somewhere in that path.

4. **Map selection can be too sticky.**  
   Heist chose map #230 in four of five runs, Assault chose map #230 in four of five runs, and Gathering chose map #149 in three of five runs. The map library works, but area/tag matching or recent-map memory needs enough variety control to avoid repetition.

5. **Infestation still has internal map accounting drift.**  
   The report sees images/VTT/`maps.html`, but the pipeline logs completion as `(N rooms, 0 maps)`. This is not a player-facing failure yet, but it means the pipeline's own map count is unreliable.

6. **The automated uniqueness scorer is still unusable.**  
   All 5-run reports still show `0.0` uniqueness. Diversity has to be judged manually until the harness compares meaningful fields like subtype, target, faction, map id, location, scene names, and outcome branches.

7. **Assassination crash is superseded by current source.**  
   The earlier 2-run batch failed on a bad regex in `_clean_json()`, but current `src\mission_builder\assassination_pipeline.py:248` uses `re.sub('[\u201c\u201d]', '"', raw)`, and the expanded 5-run batch passed 5/5. Keep the old failure as history only unless it reappears.

## Executive Summary

Source review and the expanded bakeoff now point in the same broad direction, with a few corrections: **Assassination currently works**, **Sabotage and Escort perform better in generated output than source-only review suggested**, and **Infestation has strong design bones but still needs map accounting and stub-room cleanup before it belongs in the top tier.** The strongest actual bakeoff performers were **ambush, assassination, assault, battle, defense, exploration, gathering, infiltration, heist, rescue, sabotage, puzzle, and strange occurrences**. These consistently produced runnable structure: scene order, progress tracks, checklists, clues or wave/room mechanics, useful session HTML, and in many cases working library map delivery.

Ignoring the legacy novel pipeline, the weakest actual bakeoff result is now **Discovery**. It builds but emits placeholder-style tests and no map artifacts. **First Contact**, **Negotiation**, **Recovery**, **Investigation**, and some no-map social/case modules remain playable but need tighter validation, map/handout decisions, and more specific generated content.

The most common cross-pipeline issues are:

- `None` or missing faction/opposing-faction values leak into module text.
- Maps may be planned, copied, or generated inconsistently; recent live modules sometimes have PNGs without `maps.html` links or VTT sidecars.
- Many modules have strong structure but weak playable mechanics: missing DCs, failure states, stat blocks, encounter budgets, alarm clocks, route nodes, or clue dependency graphs.
- Several social/case pipelines are good prep documents but need stronger scene-by-scene run order.
- Specialized pipelines should borrow the **published** pipeline's table-first `session.html` discipline.

## Source-Review Scorecard

This older scorecard is based on source review and earlier smoke outputs. Use the **Actual Multi-Run Bakeoff** section above for current generated-module scores, especially for Assassination, Discovery, Infestation, Escort, Battle, and Sabotage where the bakeoff changed the picture.

| Pipeline | Quality | Diversity | Playability | Verdict |
|---|---:|---:|---:|---|
| Published fallback | 8 | 6 | 9 | Best default table-first builder for unhandled types. |
| Infestation | 8 | 7 | 8 | Strongest specialist dungeon/room pipeline. |
| Assault | 8 | 7 | 8 | Very runnable morale/chokepoint assault module. |
| Defense | 8 | 7 | 8 | Strong wave-defense structure. |
| Gathering | 8 | 6 | 9 | Highly runnable logistics/session tracker. |
| Investigation | 8 | 8 | 8 | Strong clue/case structure. |
| Puzzle | 8 | 7 | 8 | Good answer key and clue ladder. |
| Exploration | 8 | 7 | 8 | Strong survey/route/session structure. |
| Heist | 8 | 9 | 7 | Best diversity engine; needs tighter mechanics. |
| Rescue | 7 | 8 | 7 | Good urgency/condition identity; needs route/clock tools. |
| Strange Occurrences | 7 | 9 | 7 | Excellent premise variety; needs ordered scenes. |
| Infiltration | 7 | 8 | 6 | Strong RP scaffold; needs DCs and dialogue branches. |
| Assassination | 7 | 6 | 6 | Solid source shape; needs smoke coverage and stat blocks. |
| Negotiation | 6 | 8 | 7 | Great balance mechanic; validation risk hurts quality. |
| Recovery | 6 | 8 | 6 | Great concept spread; fallback output too generic. |
| Ambush | 6 | 7 | 6 | Tactical idea is good; generated examples need enemies/maps. |
| Battle | 6 | 6 | 6 | Good large-fight concept; output too generic/repetitive. |
| First Contact | 6 | 5 | 7 | Usable social kit; needs unique cultures/scenes. |
| Escort | 6 | 6 | 5 | Good premise; route play is too thin. |
| Discovery | 5 | 4 | 6 | Good shell, but examples are fallback/generic. |
| Sabotage | 5 | 7 | 6 | Good categories, weak operational procedure. |

## Pipeline Notes

### Published Fallback

**Scores:** Quality 8, Diversity 6, Playability 9  
Best default table module builder for board types that do not have a specialized pipeline. It creates a clean box set with five scenes, read-aloud, DM notes, concrete DC checks, stat blocks, battlefield notes, quality report, maps manifest, and a real `session.html` runner with scene checkboxes/state.

Main weakness is sameness: the scaffold can feel similar across mission types if the optional blueprint is not specific. Add more mission-type-specific templates and make map availability explicit when no PNGs are copied.

### Infestation

**Scores:** Quality 8, Diversity 7, Playability 8  
Strong classic dungeon-style play: room sequence, monster roster, boss pass, ASCII/overview map support, chart pack, and session runner. Smoke outputs are runnable and map-heavy.

Recent `The_Iron_Scar_Contract` examples had actual PNGs but no `maps.html` and no VTT sidecars, which weakens delivery. Ensure maps are always linked from `index.html`, include room details in session view, and add stronger objectives/clues beyond "clear the room."

### Assault

**Scores:** Quality 8, Diversity 7, Playability 8  
Very table-ready: force profiles, morale pools, commander abilities, chokepoints, win conditions, and debrief inputs. It gives the DM something to actually run.

Weak spots are `None` defending factions in smoke output, map absence, and enemy units presented more as labels/counts than compact stat blocks. Enforce opposing faction resolution and add objective zones, ranges, commander turns, and usable grunt/lieutenant stat summaries.

### Defense

**Scores:** Quality 8, Diversity 7, Playability 8  
One of the cleanest action modules: prep upgrades, intel leads, morale, waves, between-wave windows, and watch events. This is a good table format.

Needs reliable attacker identity, named commanders, zone maps, and explicit wave success/failure consequences. Enemy waves also need compact stats or DDB links, not just counts.

### Gathering

**Scores:** Quality 8, Diversity 6, Playability 9  
Highly runnable: three-act structure, contact scene, quota/stock tracker, gather attempts, encounter table, reward scaling, debrief form, and live party scaling. The session value is high.

Diversity is decent through faction item profiles, but individual gather nodes can still feel like repeated checks. Give each stock node a distinct site, alternate acquisition route, faction complication, and item/handling handout.

### Investigation

**Scores:** Quality 8, Diversity 8, Playability 8  
Strong case pipeline: public story vs truth, timeline, suspects, clue web, leads with fail-forward, evidence board, accusation standard, and public/TNN pressure. This is close to run-ready.

Risks are overcomplicated clue output, noisy text, and occasional encoding weirdness. Enforce "each clue proves one thing," add a one-page clue dependency graph, and validate player-facing vs DM-only text.

### Puzzle

**Scores:** Quality 8, Diversity 7, Playability 8  
Strong DM safety: answer key, exact solution steps, clue ladder, research routes, progress track, calendar stages, puzzle board, wrong attempts, world movement, alternate solutions, and unstick notes.

It sometimes wants visual props without producing them. Add generated cipher/mural/mechanism handouts, diagrams, and stricter player-facing vs DM-only separation.

### Exploration

**Scores:** Quality 8, Diversity 7, Playability 8  
Best survey-style structure: cover, quick reference, DM setup, read-aloud scenes, six survey points, hazards, deliverables, future seeds, and a usable session checklist.

Weak spots are raw dict/mechanics rendering, non-5e skill labels such as `Diplomacy` or `Lore`, and "No map generated" for a mission type that often wants route mapping. Normalize skills and generate at least a schematic/survey map.

### Heist

**Scores:** Quality 8, Diversity 9, Playability 7  
Best diversity engine: many subtypes, casing questions, planning clock, crew assets, marks, security layers, heat, rival crews, escape twists, double-crosses, and outcome bands.

The smoke HTML is rich but still asks the DM to adjudicate too much. Make each security layer a mini-encounter with DCs, fail-forward results, NPC truth sheets, an alarm clock, and clear evidence/loot handling.

### Rescue

**Scores:** Quality 7, Diversity 8, Playability 7  
Good identity: urgency, condition track, reporter pressure, high-Kharma/low-EC framing, and active vs aftermath modes.

Sample output can conflict with fiction, such as target type drift. Add timed rescue worksheets, named victim condition clocks, rescue-specific skill challenge math, and safe/unsafe route maps.

### Strange Occurrences

**Scores:** Quality 7, Diversity 9, Playability 7  
Excellent premise variety: returned dead, doppelgangers, hauntings, Tower errors, coroner records, witness webs, faction pressure, and pay-vs-ethics outcomes.

It reads more like a case board than a session script. Add 4-6 ordered scenes, a player-facing evidence board, named suspects/occurrences, and a "when the party stalls" procedure.

### Infiltration

**Scores:** Quality 7, Diversity 8, Playability 6  
Strong RP-first scaffold: cover identities, social cast, alert track, suggested PC roles, scene sequence, and debrief state.

Generated scenes can be labels instead of playable scenes. Add per-scene prompts, NPC Wants/Knows/Hides, "if players ask" branches, suspicion DCs, and cleaner faction/site casting.

### Assassination

**Scores:** Quality 7, Diversity 6, Playability 6  
Source has a solid shape: briefing, morally complicated target, daily routine, surveillance leads, approach options, exfiltration, security profiles, and debrief.

No representative smoke module was found, so this grade is source-only. Add smoke coverage, target/guard stat blocks, abort/nonlethal branches, stronger faction moral twists, and a compact target routine handout.

### Negotiation

**Scores:** Quality 6, Diversity 8, Playability 7  
The balance-marker mechanic is excellent and gives negotiation a real gameable shape. Research lanes, favors, red lines, escalations, and outcome bands are practical.

Smoke output exposed a major validation risk: Side B can become `None`, causing nonsensical dialogue/outcomes. Require both sides, pick named delegates from NPC/faction pools, and put a visible marker-shift tracker in session HTML.

### Recovery

**Scores:** Quality 6, Diversity 8, Playability 6  
Excellent concept variety: evidence, relics, identity packets, cargo, missing pets, custody chains, rival clocks, and handling rules.

The sampled HTML is usable but fallback-heavy, with generic trail beats and unnamed holders. Add concrete retrieval locations, current holder NPCs, clue props, custody/chain-of-evidence handouts, and a tighter final handoff scene.

### Ambush

**Scores:** Quality 6, Diversity 7, Playability 6  
Good tactical premise: route secrecy, trap slots, heat states, target movement, and DM/player map separation.

Smoke HTML had `None` faction output, no real enemy stat blocks/CRs, and abstract maps unless backfill succeeds. Repair/validate factions, add guard stat blocks/tactics, surprise/initiative rules, and connect route markers to actual terrain.

### Battle

**Scores:** Quality 6, Diversity 6, Playability 6  
Good concept for large fights: conflict type, battle tide, pocket fights, glory fight, allied support, and debrief.

Output is weaker than design: repeated pocket fight names, `None Infantry`, sparse hazards, no wide battlefield map, and very large grunt counts. Add unique fight zones, mob rules, encounter budgets, faction repair, and a wide battlefield map with zones.

### First Contact

**Scores:** Quality 6, Diversity 5, Playability 7  
Useful social kit: needs, fears, taboos, panic meter, translation tracker, Tower primer, faction risks, and protection options.

It lacks a unique contact community, concrete customs, staged scenes, and enough branching trust/fear consequences. Add contact-group identity templates, visible behaviors tied to taboos, three staged encounters, and faction-specific exploitation/protection moves.

### Escort

**Scores:** Quality 6, Diversity 6, Playability 5  
Good frame: vetting, fragile/useful principals, handling rules, trap menu, ambush goal, and outcome/pay states.

Generated HTML is thin at the table: few controls, no real route map, no ambusher roster, and the ambush point is DM-chosen rather than structured. Add route-node scenes, target behavior per round, ambusher stat blocks, chase/escape rules, and stronger DM map overlays.

### Discovery

**Scores:** Quality 5, Diversity 4, Playability 6  
Good shell for containment, custody, implications, fate options, and a session tracker.

Smoke output showed fallback-level content: repeated `Test 1-5`, generic implications, and thin dialogue. Generate a named artifact/specimen, unique evidence, specific discovery scenes, escalating handling consequences, and handouts for evidence, custody, and faction claims.

### Sabotage

**Scores:** Quality 5, Diversity 7, Playability 6  
Good source categories and heat/anonymity outcomes.

Sample output exposed weak fallback behavior: `None` factions, vague failure states, duplicated marker-only map blocks, and too little DC-by-DC operation procedure. Require owner/security faction resolution, add progress-track DCs per step, define alarm/heat triggers, and produce an annotated infiltration/supply-route map or handout.

## Priority Improvements

1. **Add a shared validation gate before rendering.**  
   Reject or repair `None`, empty faction names, missing opposition, missing primary location, and generic placeholder text before HTML is written.

2. **Standardize session runners.**  
   Every pipeline should produce a run-at-table `session.html` with ordered scenes, checkboxes, clocks/tracks, DCs, complications, and debrief hooks. Published is the model.

3. **Standardize map delivery.**  
   If maps exist, `index.html` should link `maps.html`; copied map PNGs should get VTT sidecars; planned maps should be clearly separated from actual copied/generated maps.

4. **Add compact mechanical payloads.**  
   Combat/action pipelines need stat summaries, enemy tactics, encounter budgets, mob rules, alarms, clocks, and clear success/failure states.

5. **Give social/case modules ordered scene play.**  
   Investigation-adjacent modules should keep evidence boards, but also include a session order: opening scene, lead scenes, pressure scene, reveal/confrontation, aftermath.

6. **Create smoke HTML for every pipeline.**  
   Assassination lacks representative smoke output. Keep one known-good generated module per pipeline and score it as part of regression testing.

7. **Make generated content more specific.**  
   Discovery, recovery, first contact, escort, and sabotage need named NPCs, named places, concrete props, and unique scene beats instead of generic "someone can be negotiated with" fallback text.

## Best Pipelines To Build Around

- **Default all-purpose module builder:** Published fallback
- **Room/dungeon crawl:** Infestation
- **Mass combat:** Assault or Defense
- **Table logistics/objective tracking:** Gathering
- **Mystery/case play:** Investigation
- **Puzzle-centered session:** Puzzle
- **Open terrain/survey:** Exploration
- **High-variety faction job:** Heist

## Worst Current Risks

- **Most likely to waste DM prep time:** Sabotage, Escort, Discovery
- **Most likely to leak broken canon into output:** Negotiation, Ambush, Assault, Battle, Defense, Sabotage when faction resolution fails
- **Most likely to promise maps without usable map artifacts:** Published fallback map manifest paths and recent live generated modules with PNGs but missing `maps.html` or sidecars
- **Most likely to look good but require hidden DM invention:** Heist, Infiltration, Recovery, Strange Occurrences

### 2026-05-21 17:29:21 - Resource cop captured mission pipeline failure

Status: open.

Context:
- Pipeline: `mission_generation`
- Mission: `The Widow's Quiet Mark Bakeoff 1`
- Type: `assassination`
- Phase: `failed`
- Elapsed: `8.2s`
- Error: `error: unterminated character set at position 0`

Next action:
- Inspect the bot logs around this timestamp and the generated module directory, if one was created.
- Reproduce through the same mission type before patching.

### 2026-05-21 17:29:32 - Resource cop captured mission pipeline failure

Status: open.

Context:
- Pipeline: `mission_generation`
- Mission: `The Widow's Quiet Mark Bakeoff 2`
- Type: `assassination`
- Phase: `failed`
- Elapsed: `10.7s`
- Error: `error: unterminated character set at position 0`

Next action:
- Inspect the bot logs around this timestamp and the generated module directory, if one was created.
- Reproduce through the same mission type before patching.
