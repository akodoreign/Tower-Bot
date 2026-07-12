# Mission Pipeline Worklog - 2026-05-29

## Implemented This Pass

- Read `CLAUDE.md`, `MAP.md`, `.codesight/wiki/index.md`, `.codesight/wiki/overview.md`, and `.codesight/CODESIGHT.md` before source edits.
- Kept emoji/Discord display strings untouched except where existing surrounding strings already contained mojibake. New text was added as plain ASCII where possible.
- `Webpage/app.py`
  - Added `_mission_generation_context_block()` for live mission generation context.
  - Mission board generation now pulls from:
    - `news_memory` recent facts/bulletins.
    - `mission_outcomes` prior fallout.
    - `global_state.council_rulings`.
    - recent mission titles to avoid repeating tired title shapes.
  - Tightened title prompt rules:
    - Must be concrete and context-built.
    - Avoid repeating recent title rhythm/nouns.
    - Explicitly pushes away from more crowns, relics, plows, generic ledgers, generic shadows, and generic secrets unless they are exact live-context proper nouns.
  - Added a "butterfly-effect" instruction: every new mission should visibly answer a live news item, prior mission fallout, council decision, or DM brief without exposing hidden module truth.
- `src/mission_builder/investigation_pipeline.py`
  - Added a `Security Detail - Follow-up Recon` layer.
  - The layer identifies site, district, security holder, security posture, and follow-up checks for infiltration, heist, and assassination.
  - If a failed recon dossier exists for the pressure faction or district, the investigation marks security as heightened:
    - future infiltration/heist/assassination starts with more suspicion.
    - the module calls out forged papers, repeated casing, and social covers as watched behavior.
  - Security detail now appears in module HTML, session HTML, DM guide, player guide, and chart pack.
- `src/mission_builder/escort_pipeline.py`
  - Added a real route-hazard layer separate from ambush/traps.
  - Hazards use Survival, Animal Handling, Perception, Insight, or Persuasion checks.
  - Hazards are scaled to live party level and appear in module HTML, session HTML, DM guide, player guide, and chart pack.
  - Ambush remains combat/prose-driven; this adds travel pressure before/between combat beats.

## Verification

- Ran `python -m py_compile Webpage\app.py src\mission_builder\escort_pipeline.py src\mission_builder\investigation_pipeline.py`.
- Compile completed with no errors.
- Did not run broad formatters or mojibake cleanup.
- Did not touch unrelated dirty worktree files.

## Pipeline Evaluation

### Infiltration

Status: strong and already context-aware for stealth/social play.

Strengths:
- Distinct social-infiltration identity.
- Records recon dossiers for follow-up heist and assassination.
- Has cover identities, crew roles, alert/exit state, approach checks, security zones, and mission-specific scenario data.

Gaps:
- Recon outcome is first recorded at module-build time as `scouted`, then later upgraded by completion code. That is good, but investigation now needs to become another upstream source of recon signals.
- Failed infiltration already matters by not being selected as usable recon; future work should also let failed recon increase heat in heist/assassination generation, not only in investigation.

### Heist

Status: very strong for execution play.

Strengths:
- Has casing questions, planning clock, security layers, heat track, target oddities, marks/staff, rival pressure, crew assets, and execution checks.
- Consumes successful/partial prior infiltration recon and marks the dossier consumed.
- Shady-faction availability check is a good genre guard.

Gaps:
- It still generates a synthetic recon dossier if no prior recon exists. That is useful for playability, but should be clearly tagged as party casing/default intel, not world-memory intel.
- Should read failed recon dossiers to increase security layers or heat, mirroring the new investigation security posture.

### Assassination

Status: strong and already security-forward.

Strengths:
- Has target profile, daily routine, surveillance leads, moral complication, security tier, approach options, method checks, exfiltration, and prior recon support.
- Already consumes usable infiltration recon.

Gaps:
- Like heist, it should eventually read failed recon dossiers as heightened security, not only successful/partial dossiers as helpful intel.
- Could benefit from investigation-generated routine evidence as a formal parent link, not only infiltration dossiers.

### Investigation

Status: improved this pass.

Strengths:
- Multi-day clue web, witness timelines, evidence board, fail-forward checks, long-rest revelation, public pressure, and DB canon seeds.
- Reads news, outcomes, NPCs, places, missing persons, auctions, rift/resurrection/gods.

New gap closed:
- Now has a security/recon detail that can look toward infiltration, heist, and assassination and flags heightened security after failed infiltration.

Remaining gaps:
- It does not yet write a recon dossier when an investigation succeeds. That would be the next connective step if we want investigations to spawn or materially improve heist/infiltration/assassination follow-ups.

### Escort

Status: improved this pass.

Strengths:
- Target handling, vetting, ambush goal, traps, maps, delivery scene, outcomes, and live scaling.

New gap closed:
- Now has real travel-hazard checks: Survival, Animal Handling, Perception, Insight, and Persuasion.

Remaining gaps:
- Hazards are generated from local tables, not yet from weather, road closures, news, or area profiles.
- Next step should connect route hazards to live weather, district danger, and recent faction incidents.

### Battle / Assault / Ambush / Combat Pipelines

Status: intentionally combat/prose-driven; do not over-convert them into skill engines.

Strengths:
- Ambush is especially distinct: target routes, prep traps, guard roster, tactical map, escape/heat.
- Assault and battle are appropriate for fixed-position or large-scale conflict.
- Universal Skill Check Cues injection still catches checks that surface after module generation.

Gaps:
- Contextual butterfly effects should be stronger: prior failed assaults should harden future defenses; prior successful battles should alter faction morale and map control.
- Keep skill checks as support beats, not the main chassis.

### First Contact

Status: good context-preservation pipeline.

Strengths:
- Has mission-context extraction, specificity checks, panic states, tower primer, and follow-up mission types.
- Good fit for prose/social/communication tension.

Gaps:
- Should pull more directly from recent news and council rulings when deciding how frightened, exploited, or politicized the new group is.
- Could write a durable "contact state" or seed follow-up escort/negotiation/defense missions.

### Infestation

Status: intentionally combat/prose/dungeon-map-driven.

Strengths:
- Room layout, subtype selection, monster roster, room content, maps, and DB-backed monsters.
- Good as a tactical cleanup/delve pipeline.

Gaps:
- Needs stronger origin/fallout from news and previous missions: why this nest appeared here, who ignored earlier signs, and what spreads if unresolved.
- Skill Check Cues are enough for local checks; do not turn it into investigation unless the mission type says so.

### Negotiation / Discovery / Exploration / Strange Occurrences / Puzzle / Recovery / Rescue / Sabotage / Gather

Status: mixed but structurally distinct.

Strengths:
- Strange Occurrences already has context extraction, weird markers, evidence lanes, and fail-forward clue handling.
- Puzzle has skill awareness and should remain puzzle-first.
- Recovery/rescue/sabotage/gather each preserve a separate mission fantasy.

Gaps:
- All should consume the same live-world context block concept: news, previous mission outcomes, council decisions, recent titles, faction reputation, and current area state.
- Recovery and rescue should distinguish lost object/person/captive more aggressively so recovery does not become rescue.
- Sabotage should share failed-recon heat with heist/infiltration but keep its own destruction/disruption focus.
- Exploration/discovery should read area profiles and battle-map memory more directly so discoveries feel geographically persistent.

## Next Recommended Work

1. Add a shared, read-only context helper for mission pipelines so each pipeline can pull recent news, previous outcomes, council rulings, faction reputation, and recent titles without copying dashboard code.
2. Extend heist and assassination to read failed recon dossiers and raise heat/security when a prior infiltration failed. DONE 2026-05-29 continuation.
3. Let successful investigations optionally write recon dossiers for follow-up infiltration/heist/assassination. DONE 2026-05-29 continuation.
4. Connect escort route hazards to weather, district danger, area profiles, and recent local incidents.
5. Add title post-processing fallback in `api_generate_mission` so if the model still emits a banned/generic title, the backend can request or synthesize a concrete case-file title before saving.

## Continuation - 2026-05-29

Implemented more of the butterfly-effect chain:

- `src/mission_builder/heist_pipeline.py`
  - Added non-consuming failed recon lookup.
  - If a prior infiltration/investigation failed against the target owner or district, the heist now displays "Heightened Security".
  - Effect guidance: add one security layer, start Heat at Warm, and make repeated casing draw staff attention.
  - DM guide, player guide, and chart pack now carry the warning.

- `src/mission_builder/assassination_pipeline.py`
  - Added non-consuming failed recon lookup by host faction.
  - Security profile is hardened before content generation, so briefing/target/approach generation receives the heightened security profile.
  - Module output includes a failed-recon warning.
  - DM guide calls out the failed dossier and how it changes guard behavior.

- `src/mission_board.py`
  - Added `_record_investigation_recon()`.
  - Completed investigations now write `partial` recon dossiers with target_kind `intel`.
  - Failed investigations now write `failure` recon dossiers, which can harden later heist/assassination/investigation security.
  - Added this for both NPC-party outcomes and player debrief outcomes.

Verification:

- `python -m py_compile src\mission_builder\heist_pipeline.py src\mission_builder\assassination_pipeline.py src\mission_board.py`
- `pytest tests\test_heist_routing.py tests\test_investigation_pipeline.py -q`
- Result: 4 passed.
