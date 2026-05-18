# Libraries

> **Navigation aid.** Library inventory extracted via AST. Read the source files listed here before modifying exported functions.

**300 library files** across 76 modules

## Archive (83 files)

- `archive\backups_old\backups\codex_20260508_bug6_db_authoritative\src\db_api.py` — get_npc, get_all_npcs, get_npcs_by_faction, get_npcs_by_status, get_living_npcs, add_npc, …
- `archive\root_scripts\sql_refactor_setup.py` — strip_thinking, test_mysql, generate_fallback_schema, generate_db_api_code, get_npc, get_all_npcs, …
- `archive\backups_old\backups\codex_20260507_172046\app.py` — index, print_view, api_status, api_missions, api_mission_detail, api_save_draft, …
- `archive\backups_old\backups\codex_20260507_173656\app.py` — index, print_view, api_status, api_missions, api_mission_detail, api_save_draft, …
- `archive\backups_old\backups\codex_20260508_bug10_image_refs_order\Webpage\app.py` — index, print_view, api_status, api_missions, api_mission_detail, api_save_draft, …
- `archive\backups_old\backups\codex_20260508_bug9_image_ref_versions\Webpage\app.py` — index, print_view, api_status, api_missions, api_mission_detail, api_save_draft, …
- `archive\backups_old\backups\codex_20260508_bug7_gazetteer_cache\src\mission_builder\locations.py` — load_gazetteer, get_districts_by_faction, get_districts_by_danger, get_district_info, get_establishments_in_district, get_sub_areas, …
- `archive\backups_old\backups\codex_20260507_171227\news_feed.py` — get_rift_mission_fuel, check_exchange_tick, check_tia_tick, check_weather_tick, check_calendar_tick, next_interval_seconds, …
- `archive\backups_old\backups\codex_20260507_171633\news_feed.py` — get_rift_mission_fuel, check_exchange_tick, check_tia_tick, check_weather_tick, check_calendar_tick, next_interval_seconds, …
- `archive\backups_old\backups\codex_20260507_175520\src\news_feed.py` — get_rift_mission_fuel, check_exchange_tick, check_tia_tick, check_weather_tick, check_calendar_tick, next_interval_seconds, …
- `archive\backups_old\backups\codex_20260507_171633\image_ref.py` — save_npc_ref, save_npc_alt_ref, get_npc_ref, get_npc_alt_ref, pin_npc_ref, has_npc_ref, …
- `archive\backups_old\backups\codex_20260507_172046\image_ref.py` — save_npc_ref, save_npc_alt_ref, get_npc_ref, get_npc_alt_ref, pin_npc_ref, has_npc_ref, …
- `archive\backups_old\backups\codex_20260508_bug8_image_ref_lock\src\image_ref.py` — save_npc_ref, save_npc_alt_ref, get_npc_ref, get_npc_alt_ref, pin_npc_ref, has_npc_ref, …
- `archive\backups_old\backups\news_feed_new.py` — check_exchange_tick, check_tia_tick, check_weather_tick, check_calendar_tick, next_interval_seconds, next_image_interval_seconds, …
- `archive\root_scripts\migrate_data.py` — log, load_json, migrate_npcs, migrate_missions, migrate_faction_reputation, migrate_news_memory, …
- `archive\backups_old\backups\codex_20260507_171633\npc_appearance.py` — current_visual_species, species_visual_guard, get_race_sd_traits, infer_gender_tag, get_npc_appearance, get_npc_sd_prompt, …
- `archive\backups_old\backups\codex_20260507_175030\src\mimir_sync.py` — ensure_sync_table, get_sync_engine, trigger_npc_sync, trigger_faction_sync, trigger_pc_mimir_sync, run_pc_gear_run, …
- `archive\backups_old\backups\codex_20260508_bug6_db_authoritative\src\mission_builder\encounters.py` — get_max_pc_level, get_party_size, get_cr, get_encounter_budget, get_cr_xp, calculate_skill_dcs, …
- `archive\backups_old\backups\codex_20260507_171227\npc_appearance.py` — get_race_sd_traits, infer_gender_tag, get_npc_appearance, get_npc_sd_prompt, get_all_npc_names, get_all_sd_prompts, …
- `archive\backups_old\backups\providers_backup_before_stub.py` — ProviderType, ModelInfo, BaseProvider, FreeProvider, OpenAIProvider, ClaudeProvider, …
- `archive\backups_old\backups\providers_backup_before_stub_20251204100905.py` — ProviderType, ModelInfo, BaseProvider, FreeProvider, OpenAIProvider, ClaudeProvider, …
- `archive\backups_old\backups\providers_backup_before_stub_20251204100922.py` — ProviderType, ModelInfo, BaseProvider, FreeProvider, OpenAIProvider, ClaudeProvider, …
- `archive\backups_old\backups\providers_before_add_chat_completion_20251204103538.py` — ProviderType, ModelInfo, BaseProvider, FreeProvider, OpenAIProvider, ClaudeProvider, …
- `archive\backups_old\backups\providers_before_chat_async_20251204105547.py` — ProviderType, ModelInfo, BaseProvider, FreeProvider, OpenAIProvider, ClaudeProvider, …
- `archive\backups_old\backups\providers_before_clean_ollama_patch_20251204121608.py` — ProviderType, ModelInfo, BaseProvider, FreeProvider, OpenAIProvider, ClaudeProvider, …
- _…and 58 more files_

## Mission_builder (54 files)

- `src\mission_builder\locations.py` — invalidate_gazetteer_cache, load_gazetteer, get_districts_by_faction, get_districts_by_danger, get_district_info, get_establishments_in_district, …
- `src\mission_builder\npcs.py` — load_npc_roster, get_faction_leader, get_faction_leader_name, get_npcs_by_faction, get_npc_by_name, get_npcs_by_location, …
- `src\mission_builder\schemas.py` — validate_mission_module, log_validation_results, get_mission_schema, MissionMetadata, MissionContent, LocationInfo, …
- `src\mission_builder\image_generator.py` — get_image_asset, craft_battle_map_prompt, craft_creature_prompt, craft_location_prompt, render_ascii_grid_to_png, generate_single_tile, …
- `src\mission_builder\encounters.py` — get_max_pc_level, get_party_size, get_cr, get_encounter_budget, get_cr_xp, calculate_skill_dcs, …
- `src\mission_builder\rewards.py` — scale_reward, get_magic_item_tier, get_random_magic_item, calculate_gold_reward, calculate_kharma_reward, format_rewards_block, …
- `src\mission_builder\scene_dialogs.py` — build_dialog_html, build_leaving_html, extract_scenes_from_html, inject_dialogs_into_html, inject_leaving_into_html, generate_all_scene_dialogs, …
- `src\mission_builder\vtt_renderer.py` — wait_for_a1111_idle, render_vtt_battlemap, write_grid_sidecar, pretty_map_path, tactical_map_path, decode_useful_a1111_image, …
- `src\mission_builder\api.py` — generate_mission, get_mission_output_path, get_recent_missions, list_missions, generate_mission_async, generate_and_save_mission, …
- `src\mission_builder\infestation_pipeline.py` — is_infestation_mission, choose_subtype, render_infestation_module, generate_monster_roster, generate_room_batch, generate_all_rooms, …
- `src\mission_builder\mission_types.py` — get_mission_type, list_mission_types, map_difficulty_to_tier, map_difficulty_to_5e, get_difficulty_description, generate_dynamic_title, …
- `src\mission_builder\docx_builder.py` — format_module_for_docx, validate_module_data, get_output_dir, list_generated_modules, cleanup_old_modules, build_docx
- `src\mission_builder\image_integration.py` — generate_mission_with_images_sync, extract_dungeon_rooms_from_mission, example_usage, generate_mission_with_images, generate_complete_mission, update_mission_with_images
- `src\mission_builder\mimir_module.py` — render_mimir_section, create_module, enrich_monsters, enrich_items, push_documents, upload_map
- `src\mission_builder\dungeon_delve\layouts.py` — get_room_count_for_level, generate_layout, get_aesthetic_for_location, RoomPosition, DungeonLayout
- `src\mission_builder\exploration_pipeline.py` — is_exploration_mission, mark_area_historical, render_module, render_session, build_exploration_module
- `src\mission_builder\infestation_layout.py` — generate_layout, render_ascii, layout_summary, InfestationRoom, InfestationLayout
- `src\mission_builder\leads.py` — generate_lead, generate_investigation_leads, format_leads_for_prompt, format_lead_as_scene, get_approach_guidance
- `src\mission_builder\maps.py` — extract_map_scenes, build_map_prompt, generate_vtt_map, generate_module_maps, post_maps_to_channel
- `src\mission_builder\ambush_pipeline.py` — is_ambush_mission, render_ambush_module, render_ambush_session, build_ambush_module
- `src\mission_builder\assassination_pipeline.py` — is_assassination_mission, render_assassination_module, render_assassination_session, build_assassination_module
- `src\mission_builder\assault_pipeline.py` — is_assault_mission, render_assault_module, render_assault_session, build_assault_module
- `src\mission_builder\battle_pipeline.py` — is_battle_mission, render_battle_module, render_battle_session, build_battle_module
- `src\mission_builder\defense_pipeline.py` — is_defense_mission, render_defense_module, render_defense_session, build_defense_module
- `src\mission_builder\discovery_pipeline.py` — is_discovery_mission, render_module, render_session, build_discovery_module
- _…and 29 more files_

## Skills (33 files)

- `skills\slack-gif-creator\core\easing.py` — linear, ease_in_quad, ease_out_quad, ease_in_out_quad, ease_in_cubic, ease_out_cubic, …
- `skills\skill-creator\eval-viewer\generate_review.py` — get_mime_type, find_runs, build_run, embed_file, load_previous_iteration, generate_html, …
- `skills\skill-creator\scripts\aggregate_benchmark.py` — calculate_stats, load_run_results, aggregate_results, generate_benchmark, generate_markdown, main
- `skills\pdf\scripts\extract_form_field_info.py` — get_full_annotation_field_id, make_field_dict, get_field_info, write_field_info
- `skills\skill-creator\scripts\run_eval.py` — find_project_root, run_single_query, run_eval, main
- `skills\docx\scripts\office\helpers\simplify_redlines.py` — simplify_redlines, get_tracked_change_authors, infer_author
- `skills\pdf\scripts\fill_fillable_fields.py` — fill_pdf_fields, validation_error_for_field_value, monkeypatch_pydpf_method
- `skills\pdf\scripts\fill_pdf_form_with_annotations.py` — transform_from_image_coords, transform_from_pdf_coords, fill_pdf_form
- `skills\skill-creator\scripts\package_skill.py` — should_exclude, package_skill, main
- `skills\skill-creator\scripts\run_loop.py` — split_eval_set, run_loop, main
- `skills\slack-gif-creator\core\frame_composer.py` — draw_circle, create_gradient_background, draw_star
- `skills\docx\scripts\office\soffice.py` — get_soffice_env, run_soffice
- `skills\pdf\scripts\check_bounding_boxes.py` — get_bounding_box_messages, RectAndField
- `skills\pdf\scripts\extract_form_structure.py` — extract_form_structure, main
- `skills\skill-creator\scripts\generate_report.py` — generate_html, main
- `skills\skill-creator\scripts\improve_description.py` — improve_description, main
- `skills\slack-gif-creator\core\validators.py` — validate_gif, is_slack_ready
- `skills\webapp-testing\scripts\with_server.py` — is_server_ready, main
- `skills\docx\scripts\accept_changes.py` — accept_changes
- `skills\docx\scripts\comment.py` — add_comment
- `skills\docx\scripts\office\helpers\merge_runs.py` — merge_runs
- `skills\docx\scripts\office\pack.py` — pack
- `skills\docx\scripts\office\unpack.py` — unpack
- `skills\docx\scripts\office\validate.py` — main
- `skills\docx\scripts\office\validators\base.py` — BaseSchemaValidator
- _…and 8 more files_

## Scripts (24 files)

- `scripts\build_creature_staging.py` — parse_cr, cr_to_str, cr_to_prof, norm_size, norm_type, hp_die_for_size, …
- `scripts\npc_ddb_builder.py` — species_to_type_size, items_to_traits, build_actions, build_traits, build_reactions, build_bonus_actions, …
- `scripts\enrich_creatures_ddb.py` — log, get_or_generate_portrait, get_or_generate_npc_portrait, enrich_creature, run_pass, main
- `scripts\import_npcs_to_ddb.py` — log, add_speed, create_npc, get_or_generate_portrait, main
- `scripts\update_ebp_content.py` — log, add_speed, edit_full, create_new, main
- `scripts\fix_ebp_types_and_art.py` — generate_art, edit_monster_ddb, main
- `scripts\backfill_discord_location_scenes.py` — main, run
- `scripts\backfill_discord_npc_portraits.py` — main, run
- `scripts\backfill_infestation_room_maps.py` — backfill_module, main
- `scripts\build_modules_saturday.py` — build_contract, build_flame
- `scripts\retry_module_gen.py` — post_module_rest, main
- `scripts\survey_ddb_import_candidates.py` — jload, main
- `scripts\backfill_module_tactical_maps.py` — main
- `scripts\check_mimir.py` — jload
- `scripts\experiment_map_lanes.py` — main
- `scripts\gearrun_mimir.py` — main
- `scripts\import_ebp_to_ddb.py` — main
- `scripts\probe_ddb_edit.py` — probe_edit
- `scripts\probe_ddb_fields.py` — probe
- `scripts\probe_mimir_npc.py` — jload
- `scripts\purge_channel.py` — purge
- `scripts\retry_map_pretty.py` — post_file_to_discord
- `scripts\survey_mission_creatures.py` — jload
- `scripts\sweep_all_missions.py` — run

## Campaign_docs (15 files)

- `campaign_docs\TrainingPDFS\extract_images.py` — file_hash, slugify, unique_slug
- `campaign_docs\TrainingPDFS\dump_chapter5.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_chapter5b.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level4.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level4_sb2.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level4_statblocks.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level5.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level5_sb.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level6.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level6b.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level6_sb.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level6_sb2.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level7_details.py` — dump_range
- `campaign_docs\TrainingPDFS\dump_level7_sb.py` — dump_range
- `campaign_docs\TrainingPDFS\extract_level2.py` — dump_range

## Cogs (10 files)

- `src\cogs\module_gen.py` — setup, generate_and_post_module
- `src\cogs\admin.py` — setup
- `src\cogs\character.py` — setup
- `src\cogs\chat.py` — setup
- `src\cogs\economy.py` — setup
- `src\cogs\images.py` — setup
- `src\cogs\missions.py` — setup
- `src\cogs\rules_lookup.py` — setup
- `src\cogs\skills.py` — setup
- `src\cogs\world.py` — setup

## Agents (8 files)

- `src\agents\learning_agents.py` — AgentAnalysis, LearningSession, ProjectManagerAgent, PythonVeteranAgent, DNDExpertAgent, DNDVeteranAgent, …
- `src\agents\news_agents.py` — get_news_agent, generate_news_bulletin, generate_gossip_bulletin, generate_sports_bulletin, FactCheckerMixin, BulletinResult, …
- `src\agents\base.py` — quick_complete, ModelType, AgentConfig, AgentResponse, BaseAgent
- `src\agents\helpers.py` — generate_with_qwen, generate_with_kimi, generate_bulletin, generate_mission_text
- `src\agents\guild_council.py` — CouncilRuling, CouncilSession, GuildCouncil
- `src\agents\kimi_agent.py` — KimiAgent
- `src\agents\orchestrator.py` — AgentOrchestrator
- `src\agents\qwen_agent.py` — QwenAgent

## Competitions (4 files)

- `src\competitions\bracket_engine.py` — create_competition, get_active_competitions, get_pending_rounds, is_pc_round, auto_resolve_npc_match, record_pc_result, …
- `src\competitions\competition_types.py` — get_competition_type, list_competition_types, RoundPhase, CompetitionType
- `src\competitions\post_competition.py` — format_bracket_announcement, format_npc_result_bulletin, format_champion_bulletin, check_competition_tick
- `src\competitions\mission_builder.py` — generate_round_module, build_round_mission

## Auto_login (2 files)

- `auto_login\AutoLogin.py` — GoogleBardAutoLogin, MicrosoftBingAutoLogin
- `auto_login\AutoLoginTest.py` — GoogleBardTest, MicrosoftBingAutoLoginTest

## A1111_runtime.py (1 files)

- `src\a1111_runtime.py` — ensure_a1111_model, cool_down_a1111_after_generation

## Aclient.py (1 files)

- `src\aclient.py` — DiscordClient

## Ad_feed.py (1 files)

- `src\ad_feed.py` — check_ad_tick, format_ad_embed, get_next_ad, generate_dynamic_ad

## Archive_logs.py (1 files)

- `src\archive_logs.py` — ensure_archive_dir, parse_log_events, generate_summary, archive_log

## Area_generator.py (1 files)

- `src\area_generator.py` — get_area_profile, get_all_district_names, get_area_map_path, generate_area_profile, generate_all_area_profiles

## Area_map_generator.py (1 files)

- `src\area_map_generator.py` — collect_areas_to_map, list_area_maps, build_area_prompt, generate_area_map_batch

## Area_places.py (1 files)

- `src\area_places.py` — generate_places_for_district, generate_all_new_areas

## Arena_season.py (1 files)

- `src\arena_season.py` — format_match_bulletin, should_post_arena, format_standings_bulletin, tick_arena

## Art.py (1 files)

- `src\art.py` — get_image_provider, draw

## Bot.py (1 files)

- `src\bot.py` — run_discord_bot

## Bounty_board.py (1 files)

- `src\bounty_board.py` — should_post_bounty, format_bounty_news_bulletin, generate_bounty_post, check_bounty_expirations

## Bulletin_cleaner.py (1 files)

- `src\bulletin_cleaner.py` — strip_llm_reasoning, filter_ec_references, is_truncated, validate_bulletin, clean_bulletin, repair_incomplete_bulletin, …

## Bulletin_embeds.py (1 files)

- `src\bulletin_embeds.py` — wrap_bulletin, wrap_bulletin_with_title

## Character_monitor.py (1 files)

- `src\character_monitor.py` — run_character_monitor

## Character_profiles.py (1 files)

- `src\character_profiles.py` — load_character_profile, save_character_profile, has_character_profile, load_character_appearance, load_character_name, save_character_appearance, …

## Check_a1111_models.py (1 files)

- `check_a1111_models.py` — main

## City_scene.py (1 files)

- `src\city_scene.py` — generate_city_scene

## Db_api.py (1 files)

- `src\db_api.py` — get_npc, get_all_npcs, get_npcs_by_faction, get_npcs_by_status, get_living_npcs, add_npc, …

## Db_backup.py (1 files)

- `src\db_backup.py` — run_backup, db_backup_loop

## Ddb_homebrew.py (1 files)

- `src\ddb_homebrew.py` — shutdown_chrome, ensure_chrome, push_monster, push_monster_http, push_mission_enemy

## Dome_weather.py (1 files)

- `src\dome_weather.py` — tick_weather, format_weather_bulletin, should_post_weather, mark_weather_posted

## Ec_exchange.py (1 files)

- `src\ec_exchange.py` — get_rate, tick_exchange, apply_event_shock, format_exchange_line, format_exchange_bulletin, format_price_table, …

## Expandable_bulletin.py (1 files)

- `src\expandable_bulletin.py` — get_archived_headlines, store_bulletin, get_bulletin, create_preview_embed, create_expanded_embed, create_bulletin_message, …

## Faction_calendar.py (1 files)

- `src\faction_calendar.py` — tick_calendar, format_event_announce, get_pending_mission_spawns, mark_mission_spawned, get_mission_params, format_event_result

## Faction_reputation.py (1 files)

- `src\faction_reputation.py` — get_faction_color, get_faction_tier_label, get_all_reputations, get_reputation, on_mission_complete, on_mission_failed, …

## Fallen_adventurers.py (1 files)

- `src\fallen_adventurers.py` — generate_fallen_bulletin, check_fallen_day_tick

## Image_ref.py (1 files)

- `src\image_ref.py` — save_npc_ref, save_npc_alt_ref, get_npc_ref, get_npc_alt_ref, pin_npc_ref, has_npc_ref, …

## Log.py (1 files)

- `src\log.py` — setup_logger, CustomFormatter

## Main.py (1 files)

- `main.py` — validate_environment, main

## Memory_strip.py (1 files)

- `src\memory_strip.py` — strip_to_facts, clean_memory_file

## Mimir_client.py (1 files)

- `src\mimir_client.py` — get_mimir, MimirClient

## Mimir_sync.py (1 files)

- `src\mimir_sync.py` — ensure_sync_table, get_sync_engine, trigger_npc_sync, trigger_faction_sync, trigger_pc_mimir_sync, run_pc_gear_run, …

## Missing_persons.py (1 files)

- `src\missing_persons.py` — should_post_missing, tick_missing_resolutions, generate_missing_bulletin

## Mission_board.py (1 files)

- `src\mission_board.py` — next_personal_mission_seconds, next_trickle_seconds, refresh_mission_types_if_needed, post_hostile_mission, post_personal_mission, check_claims, …

## Mission_compiler.py (1 files)

- `src\mission_compiler.py` — build_mission_json, compile_mission, MissionCompiler

## Mission_outcomes.py (1 files)

- `src\mission_outcomes.py` — get_recent_outcomes, save_outcome, archive_news_weekly, archive_outcomes_weekly, process_npc_deaths, process_outcome_consequences

## Module_quality_trainer.py (1 files)

- `src\module_quality_trainer.py` — study_module_quality

## News_feed.py (1 files)

- `src\news_feed.py` — get_rift_mission_fuel, check_exchange_tick, check_tia_tick, check_weather_tick, check_calendar_tick, next_interval_seconds, …

## News_integration.py (1 files)

- `src\news_integration.py` — get_timestamp_line, generate_editorial_bulletin, generate_gossip_only, generate_sports_only, post_editorial_bulletin, generate_for_command, …

## Npc_appearance.py (1 files)

- `src\npc_appearance.py` — current_visual_species, species_visual_guard, species_portrait_constraints, get_race_sd_traits, infer_gender_tag, get_npc_appearance, …

## Npc_consequence.py (1 files)

- `src\npc_consequence.py` — scan_bulletin_for_consequences, apply_consequences, check_resurrection_queue, check_resurrection_queue, resurrect_npc, get_recently_deceased_block, …

## Npc_lifecycle.py (1 files)

- `src\npc_lifecycle.py` — get_home_district, is_faction_leader, get_leader_faction, is_unknown_party_member, get_party_member_data, next_lifecycle_seconds, …

## Npc_lookup.py (1 files)

- `src\npc_lookup.py` — extract_quoted_names, extract_and_lookup_npcs, get_npc_context_for_prompt, get_npc_sd_prompt, lookup_npc_by_name

## Npc_statblock_backfill.py (1 files)

- `src\npc_statblock_backfill.py` — backfill_one, run_statblock_backfill

## Nudge_state.py (1 files)

- `src\nudge_state.py` — has_been_nudged, mark_nudged

## Ollama_busy.py (1 files)

- `src\ollama_busy.py` — is_available, is_priority_busy, get_busy_reason, mark_busy, mark_available, mark_priority_busy, …

## Ollama_queue.py (1 files)

- `src\ollama_queue.py` — call_ollama, call_ollama_quick, OllamaBusyError

## Party_interview.py (1 files)

- `src\party_interview.py` — score_epic, pick_sponsor, archive_expired_interviews, generate_interview, maybe_trigger_interview

## Party_profiles.py (1 files)

- `src\party_profiles.py` — load_profile, save_profile, get_party_delta, apply_party_outcome, is_exceptional_outcome, profile_summary, …

## Patch_approval.py (1 files)

- `src\patch_approval.py` — parse_pending_patches, update_patch_status, setup, PatchApprovalView, PatchListView

## Personas.py (1 files)

- `src\personas.py` — get_persona_prompt, is_jailbreak_persona, is_admin_user, get_available_personas

## Player_listings.py (1 files)

- `src\player_listings.py` — tick_player_listings, place_bid_on_player_listing, buy_now_player_listing, create_listing, format_player_listings_embed, format_sold_notification

## Providers.py (1 files)

- `src\providers.py` — ProviderType, ModelInfo, BaseProvider, FreeProvider, OpenAIProvider, ClaudeProvider, …

## Rag_sanity_check.py (1 files)

- `src\rag_sanity_check.py` — main

## Resource_cop.py (1 files)

- `src\resource_cop.py` — active_pipelines_sync, ask_a1111_sync, start_pipeline, set_pipeline_phase, finish_pipeline, append_pipeline_failure, …

## Rules_agent.py (1 files)

- `src\rules_agent.py` — answer_rules_question, lookup_spell_or_feature, RulesAnswer

## Self_learning.py (1 files)

- `src\self_learning.py` — run_learning_session, self_learning_loop

## Skill_loader.py (1 files)

- `src\skill_loader.py` — load_skills, save_skill_to_db, score_skill, match_skills, format_skills_for_prompt, get_skill_inventory, …

## Skills.py (1 files)

- `src\skills.py` — load_skill_from_file, load_all_skills, get_skill_for_task, list_available_skills, get_skill_content, build_system_prompt_with_skills, …

## Style_agent.py (1 files)

- `src\style_agent.py` — faction_style_summary, describe_character_style, enrich_appearance_prompt

## Text_mojibake.py (1 files)

- `src\text_mojibake.py` — repair_mojibake, repair_payload

## Tower_economy.py (1 files)

- `src\tower_economy.py` — react_to_bulletin, format_towerbay_bulletin, tick_tia, format_tia_bulletin, format_towerbay_embeds, place_bid, …

## Tower_rag.py (1 files)

- `src\tower_rag.py` — get_relevant_chunks, build_context_from_messages, search_docs, Intent

## Tts_engine.py (1 files)

- `src\tts_engine.py` — generate_tts_audio

## Utils (1 files)

- `utils\message_utils.py` — send_split_message, send_response_with_images

## Webpage (1 files)

- `Webpage\app.py` — index, print_view, api_status, api_missions, api_mission_detail, api_claim_mission, …

## Weekly_archive.py (1 files)

- `src\weekly_archive.py` — run_weekly_archive, load_archive, load_all_archives, search_archive, list_archive_weeks, archive_summary

---
_Back to [overview.md](./overview.md)_