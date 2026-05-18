# MySQL Schema Reference

Generated: 2026-05-17T15:46:11
Database: `tower_bot`
Tables: 43

This file is generated from live MySQL metadata. MySQL is authoritative; prefer `src.db_api.raw_query`, `raw_execute`, `get_global_state`, and `set_global_state` over legacy JSON/text files.

## Table List

- `adventurer_parties`
- `area_profiles`
- `arena_seasons`
- `bot_commands`
- `bounties`
- `bulletin_cache`
- `character_snapshots`
- `competition_entries`
- `competitions`
- `economy_state`
- `faction_events`
- `faction_reputation`
- `gazetteer`
- `gazetteer_places`
- `global_state`
- `gods`
- `image_refs`
- `lifecycle_daily_events`
- `lifecycle_events`
- `mimir_sync`
- `missing_persons`
- `mission_outcomes`
- `mission_type_templates`
- `mission_types`
- `missions`
- `news_entries`
- `news_memory`
- `news_types`
- `npc_appearances`
- `npcs`
- `party_interviews`
- `party_profiles`
- `personal_missions`
- `player_characters`
- `player_listings`
- `resurrection_queue`
- `rift_state`
- `skills`
- `tia_market`
- `towerbay_auctions`
- `towerbay_bids`
- `training_docs`
- `weather_state`

## Tables

### `adventurer_parties`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `party_name` | `varchar(500)` | NO | `` | `UNI` | `` |  |
| `added_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |

Indexes:
- `party_name` (UNIQUE, BTREE): `party_name`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `area_profiles`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `district` | `varchar(200)` | NO | `` | `UNI` | `` |  |
| `profile_json` | `json` | YES | `` | `` | `` |  |
| `generated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |

Indexes:
- `district` (UNIQUE, BTREE): `district`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `arena_seasons`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `season_number` | `int` | YES | `` | `` | `` |  |
| `champion_name` | `varchar(255)` | YES | `` | `` | `` |  |
| `champions_json` | `json` | YES | `` | `` | `` |  |
| `standings_json` | `json` | YES | `` | `` | `` |  |
| `started_at` | `datetime` | YES | `` | `` | `` |  |
| `ended_at` | `datetime` | YES | `` | `` | `` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`

### `bot_commands`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `command_name` | `varchar(100)` | NO | `` | `UNI` | `` |  |
| `description` | `text` | YES | `` | `` | `` |  |
| `source_file` | `varchar(255)` | YES | `` | `` | `` |  |
| `source_function` | `varchar(255)` | YES | `` | `` | `` |  |
| `cog_name` | `varchar(100)` | YES | `` | `` | `` |  |
| `dm_only` | `tinyint(1)` | YES | `0` | `` | `` |  |
| `parameters` | `json` | YES | `` | `` | `` |  |
| `notes` | `text` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |

Indexes:
- `command_name` (UNIQUE, BTREE): `command_name`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `bounties`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `title` | `varchar(255)` | NO | `` | `` | `` |  |
| `target_type` | `varchar(50)` | YES | `` | `` | `` |  |
| `target_name` | `varchar(255)` | YES | `` | `` | `` |  |
| `reward_ec` | `int` | YES | `0` | `` | `` |  |
| `status` | `varchar(50)` | YES | `active` | `MUL` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `claimed_by` | `varchar(255)` | YES | `` | `` | `` |  |

Indexes:
- `idx_status` (INDEX, BTREE): `status`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `bulletin_cache`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `bulletin_id` | `varchar(16)` | NO | `` | `UNI` | `` |  |
| `payload` | `json` | NO | `` | `` | `` |  |
| `status` | `enum('active','archived')` | NO | `active` | `MUL` | `` |  |
| `created_at` | `datetime` | NO | `CURRENT_TIMESTAMP` | `MUL` | `DEFAULT_GENERATED` |  |

Indexes:
- `bulletin_id` (UNIQUE, BTREE): `bulletin_id`
- `idx_created_at` (INDEX, BTREE): `created_at`
- `idx_status` (INDEX, BTREE): `status`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `character_snapshots`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `char_id` | `bigint` | NO | `` | `MUL` | `` |  |
| `char_name` | `varchar(255)` | NO | `` | `` | `` |  |
| `player` | `varchar(100)` | YES | `` | `` | `` |  |
| `snapshot_json` | `json` | YES | `` | `` | `` |  |
| `fetched_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `MUL` | `DEFAULT_GENERATED` |  |

Indexes:
- `idx_char_fetched` (INDEX, BTREE): `char_id`, `fetched_at`
- `idx_char_id` (INDEX, BTREE): `char_id`
- `idx_fetched` (INDEX, BTREE): `fetched_at`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `competition_entries`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `comp_id` | `int` | NO | `` | `MUL` | `` |  |
| `name` | `varchar(128)` | NO | `` | `` | `` |  |
| `entry_type` | `enum('pc','npc')` | NO | `` | `` | `` |  |
| `faction` | `varchar(128)` | YES | `` | `` | `` |  |
| `seed` | `int` | YES | `0` | `` | `` |  |
| `status` | `enum('active','eliminated','champion')` | YES | `active` | `MUL` | `` |  |
| `round_reached` | `int` | YES | `0` | `` | `` |  |
| `wins` | `int` | YES | `0` | `` | `` |  |
| `losses` | `int` | YES | `0` | `` | `` |  |
| `notes` | `text` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |

Indexes:
- `idx_comp` (INDEX, BTREE): `comp_id`
- `idx_status` (INDEX, BTREE): `status`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `competitions`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `slug` | `varchar(64)` | NO | `` | `` | `` |  |
| `name` | `varchar(255)` | NO | `` | `` | `` |  |
| `sponsor` | `varchar(128)` | NO | `` | `` | `` |  |
| `status` | `enum('upcoming','active','complete')` | YES | `upcoming` | `` | `` |  |
| `current_round` | `int` | YES | `0` | `` | `` |  |
| `bracket_json` | `mediumtext` | YES | `` | `` | `` |  |
| `started_at` | `datetime` | YES | `` | `` | `` |  |
| `completed_at` | `datetime` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`

### `economy_state`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `ec_to_kharma_rate` | `decimal(10,4)` | YES | `1.0000` | `` | `` |  |
| `trend` | `varchar(50)` | YES | `` | `` | `` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`

### `faction_events`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `faction` | `varchar(100)` | YES | `` | `MUL` | `` |  |
| `event_type` | `varchar(100)` | YES | `` | `` | `` |  |
| `emoji` | `varchar(50)` | YES | `` | `` | `` |  |
| `event_date` | `datetime` | YES | `` | `MUL` | `` |  |
| `description` | `text` | YES | `` | `` | `` |  |

Indexes:
- `idx_date` (INDEX, BTREE): `event_date`
- `idx_faction` (INDEX, BTREE): `faction`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `faction_reputation`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `faction_name` | `varchar(100)` | NO | `` | `UNI` | `` |  |
| `reputation_score` | `int` | YES | `0` | `` | `` |  |
| `tier` | `varchar(50)` | YES | `` | `` | `` |  |
| `last_updated` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |
| `leader` | `varchar(200)` | YES | `` | `` | `` |  |
| `location_name` | `varchar(100)` | YES | `` | `` | `` |  |
| `description` | `text` | YES | `` | `` | `` |  |
| `motto` | `varchar(200)` | YES | `` | `` | `` |  |

Indexes:
- `faction_name` (UNIQUE, BTREE): `faction_name`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `gazetteer`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `content_json` | `longtext` | YES | `` | `` | `` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`

### `gazetteer_places`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `district` | `varchar(100)` | NO | `` | `MUL` | `` |  |
| `place_type` | `enum('place_of_interest','small_shop','park','mall')` | NO | `` | `MUL` | `` |  |
| `name` | `varchar(200)` | NO | `` | `` | `` |  |
| `type_tag` | `varchar(100)` | YES | `` | `` | `` |  |
| `description` | `text` | YES | `` | `` | `` |  |
| `extra_json` | `json` | YES | `` | `` | `` |  |
| `wealth_level` | `tinyint` | NO | `5` | `` | `` | 1=destitute 10=elite |

Indexes:
- `idx_district` (INDEX, BTREE): `district`
- `idx_type` (INDEX, BTREE): `place_type`
- `PRIMARY` (PRIMARY, BTREE): `id`
- `uq_place` (UNIQUE, BTREE): `district`, `place_type`, `name`

### `global_state`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `state_key` | `varchar(100)` | NO | `` | `UNI` | `` |  |
| `state_value` | `json` | YES | `` | `` | `` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |

Indexes:
- `idx_key` (INDEX, BTREE): `state_key`
- `PRIMARY` (PRIMARY, BTREE): `id`
- `state_key` (UNIQUE, BTREE): `state_key`

### `gods`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `name` | `varchar(200)` | NO | `` | `UNI` | `` |  |
| `origin` | `varchar(200)` | YES | `` | `` | `` |  |
| `domain` | `text` | YES | `` | `` | `` |  |
| `god_type` | `varchar(100)` | YES | `` | `` | `` |  |
| `alliance` | `varchar(100)` | YES | `` | `` | `` |  |
| `alignment` | `varchar(10)` | YES | `` | `` | `` |  |
| `faithlight` | `int` | YES | `0` | `` | `` |  |
| `total_kharma` | `int` | YES | `0` | `` | `` |  |
| `cleric_start` | `int` | YES | `0` | `` | `` |  |
| `cycle_origin` | `int` | YES | `1` | `` | `` |  |
| `recruit_risk` | `int` | YES | `50` | `` | `` |  |
| `role_function` | `varchar(200)` | YES | `` | `` | `` |  |
| `notes` | `text` | YES | `` | `` | `` |  |
| `charitable` | `tinyint` | YES | `0` | `` | `` |  |
| `charity_style` | `varchar(100)` | YES | `` | `` | `` |  |
| `suspicious` | `tinyint` | YES | `0` | `` | `` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`
- `uq_name` (UNIQUE, BTREE): `name`

### `image_refs`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `entity_type` | `varchar(50)` | NO | `` | `MUL` | `` |  |
| `entity_name` | `varchar(255)` | NO | `` | `` | `` |  |
| `image_path` | `varchar(500)` | YES | `` | `` | `` |  |
| `ref_count` | `int` | YES | `1` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `metadata_json` | `json` | YES | `` | `` | `` |  |
| `updated_at` | `datetime` | YES | `` | `` | `` |  |

Indexes:
- `idx_entity` (INDEX, BTREE): `entity_type`, `entity_name`
- `PRIMARY` (PRIMARY, BTREE): `id`
- `unique_entity` (UNIQUE, BTREE): `entity_type`, `entity_name`

### `lifecycle_daily_events`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `event_date` | `date` | NO | `` | `UNI` | `` |  |
| `events_json` | `json` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |

Indexes:
- `event_date` (UNIQUE, BTREE): `event_date`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `lifecycle_events`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `event_type` | `varchar(100)` | NO | `` | `MUL` | `` |  |
| `npc_name` | `varchar(255)` | YES | `` | `` | `` |  |
| `event_data_json` | `json` | YES | `` | `` | `` |  |
| `occurred_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `MUL` | `DEFAULT_GENERATED` |  |

Indexes:
- `idx_occurred` (INDEX, BTREE): `occurred_at`
- `idx_type` (INDEX, BTREE): `event_type`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `mimir_sync`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `entity_type` | `varchar(32)` | NO | `` | `MUL` | `` |  |
| `entity_id` | `varchar(128)` | NO | `` | `` | `` |  |
| `mimir_id` | `varchar(128)` | YES | `` | `` | `` |  |
| `sync_hash` | `varchar(32)` | YES | `` | `` | `` |  |
| `synced_at` | `timestamp` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`
- `uq_entity` (UNIQUE, BTREE): `entity_type`, `entity_id`

### `missing_persons`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `person_name` | `varchar(255)` | NO | `` | `` | `` |  |
| `last_seen_location` | `varchar(255)` | YES | `` | `` | `` |  |
| `reported_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `status` | `varchar(50)` | YES | `missing` | `MUL` | `` |  |
| `found_at` | `datetime` | YES | `` | `` | `` |  |

Indexes:
- `idx_status` (INDEX, BTREE): `status`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `mission_outcomes`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `mission_title` | `varchar(500)` | YES | `` | `` | `` |  |
| `faction` | `varchar(255)` | YES | `` | `` | `` |  |
| `opposing_faction` | `varchar(255)` | YES | `` | `` | `` |  |
| `tier` | `varchar(100)` | YES | `` | `` | `` |  |
| `completed_by` | `varchar(255)` | YES | `` | `` | `` |  |
| `completed_at` | `varchar(50)` | YES | `` | `` | `` |  |
| `result` | `varchar(50)` | YES | `` | `` | `` |  |
| `npcs_killed` | `text` | YES | `` | `` | `` |  |
| `key_decisions` | `text` | YES | `` | `` | `` |  |
| `location_changes` | `text` | YES | `` | `` | `` |  |
| `loose_threads` | `text` | YES | `` | `` | `` |  |
| `notable_moments` | `text` | YES | `` | `` | `` |  |
| `consequences_json` | `json` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`

### `mission_type_templates`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `slug` | `varchar(64)` | NO | `` | `UNI` | `` |  |
| `display_name` | `varchar(128)` | NO | `` | `` | `` |  |
| `who` | `text` | NO | `` | `` | `` |  |
| `what` | `text` | NO | `` | `` | `` |  |
| `when_hint` | `text` | NO | `` | `` | `` |  |
| `why` | `text` | NO | `` | `` | `` |  |
| `where_hint` | `text` | NO | `` | `` | `` |  |
| `story_frame` | `text` | NO | `` | `` | `` |  |
| `keywords` | `varchar(512)` | YES | `` | `` | `` |  |
| `created_at` | `timestamp` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `combat_posture` | `varchar(16)` | YES | `PERMITTED` | `` | `` |  |
| `combat_rep_cost` | `text` | YES | `` | `` | `` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`
- `slug` (UNIQUE, BTREE): `slug`

### `mission_types`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `type_name` | `varchar(100)` | NO | `` | `UNI` | `` |  |
| `template` | `text` | YES | `` | `` | `` |  |
| `difficulty_range` | `varchar(50)` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `usage_count` | `int` | YES | `0` | `` | `` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`
- `type_name` (UNIQUE, BTREE): `type_name`

### `missions`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `title` | `varchar(255)` | NO | `` | `` | `` |  |
| `description` | `text` | YES | `` | `` | `` |  |
| `difficulty` | `varchar(50)` | YES | `` | `` | `` |  |
| `faction` | `varchar(100)` | YES | `` | `MUL` | `` |  |
| `npc_giver` | `varchar(255)` | YES | `` | `` | `` |  |
| `status` | `enum('active','claimed','completed','expired','failed')` | YES | `active` | `MUL` | `` |  |
| `reward_ec` | `int` | YES | `0` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `expires_at` | `datetime` | YES | `` | `` | `` |  |
| `claimed_by` | `varchar(255)` | YES | `` | `` | `` |  |
| `completed_at` | `datetime` | YES | `` | `` | `` |  |
| `message_id` | `varchar(50)` | YES | `` | `` | `` |  |
| `tier` | `varchar(50)` | YES | `` | `` | `` |  |
| `posted_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `mission_json` | `json` | YES | `` | `` | `` |  |
| `module_slug` | `varchar(200)` | YES | `` | `` | `` |  |

Indexes:
- `idx_faction` (INDEX, BTREE): `faction`
- `idx_status` (INDEX, BTREE): `status`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `news_entries`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `headline` | `varchar(500)` | NO | `` | `` | `` |  |
| `body` | `text` | YES | `` | `` | `` |  |
| `category` | `varchar(100)` | YES | `` | `MUL` | `` |  |
| `posted_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `MUL` | `DEFAULT_GENERATED` |  |
| `news_type` | `varchar(100)` | YES | `` | `` | `` |  |
| `message_id` | `varchar(50)` | YES | `` | `` | `` |  |

Indexes:
- `idx_category` (INDEX, BTREE): `category`
- `idx_posted` (INDEX, BTREE): `posted_at`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `news_memory`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `bulletin_text` | `text` | YES | `` | `` | `` |  |
| `facts` | `text` | YES | `` | `` | `` |  |
| `news_type` | `varchar(100)` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `MUL` | `DEFAULT_GENERATED` |  |

Indexes:
- `idx_created` (INDEX, BTREE): `created_at`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `news_types`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `type_name` | `varchar(100)` | NO | `` | `UNI` | `` |  |
| `template` | `text` | YES | `` | `` | `` |  |
| `weight` | `decimal(5,2)` | YES | `1.00` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `usage_count` | `int` | YES | `0` | `` | `` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`
- `type_name` (UNIQUE, BTREE): `type_name`

### `npc_appearances`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `npc_name` | `varchar(255)` | NO | `` | `UNI` | `` |  |
| `appearance_prompt` | `text` | YES | `` | `` | `` |  |
| `style` | `varchar(50)` | YES | `` | `` | `` |  |
| `generated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `appearance_json` | `json` | YES | `` | `` | `` |  |
| `sd_prompt` | `text` | YES | `` | `` | `` |  |

Indexes:
- `npc_name` (UNIQUE, BTREE): `npc_name`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `npcs`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `name` | `varchar(255)` | NO | `` | `UNI` | `` |  |
| `faction` | `varchar(100)` | YES | `` | `MUL` | `` |  |
| `role` | `text` | YES | `` | `` | `` |  |
| `location` | `varchar(255)` | YES | `` | `MUL` | `` |  |
| `description` | `text` | YES | `` | `` | `` |  |
| `arrival_date` | `datetime` | YES | `` | `` | `` |  |
| `status` | `varchar(50)` | YES | `alive` | `MUL` | `` |  |
| `appearance_json` | `json` | YES | `` | `` | `` |  |
| `data_json` | `json` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |
| `deceased_at` | `datetime` | YES | `` | `` | `` |  |
| `species` | `varchar(100)` | YES | `` | `` | `VIRTUAL GENERATED` |  |

Indexes:
- `idx_faction` (INDEX, BTREE): `faction`
- `idx_location` (INDEX, BTREE): `location`
- `idx_status` (INDEX, BTREE): `status`
- `name` (UNIQUE, BTREE): `name`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `party_interviews`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `mission_title` | `varchar(500)` | YES | `` | `` | `` |  |
| `party_name` | `varchar(255)` | YES | `` | `MUL` | `` |  |
| `sponsor_name` | `varchar(200)` | YES | `` | `` | `` |  |
| `sponsor_district` | `varchar(100)` | YES | `` | `` | `` |  |
| `interview_text` | `longtext` | YES | `` | `` | `` |  |
| `discord_message_id` | `varchar(50)` | YES | `` | `` | `` |  |
| `epic_score` | `int` | YES | `0` | `` | `` |  |
| `posted_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `expires_at` | `datetime` | YES | `` | `` | `` |  |
| `archived` | `tinyint(1)` | YES | `0` | `MUL` | `` |  |
| `archived_at` | `datetime` | YES | `` | `` | `` |  |

Indexes:
- `idx_archived` (INDEX, BTREE): `archived`, `expires_at`
- `idx_party` (INDEX, BTREE): `party_name`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `party_profiles`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `party_name` | `varchar(255)` | NO | `` | `UNI` | `` |  |
| `members_json` | `json` | YES | `` | `` | `` |  |
| `reputation` | `int` | YES | `0` | `` | `` |  |
| `formed_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `status` | `varchar(50)` | YES | `active` | `` | `` |  |
| `profile_json` | `json` | YES | `` | `` | `` |  |

Indexes:
- `party_name` (UNIQUE, BTREE): `party_name`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `personal_missions`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `character_name` | `varchar(255)` | NO | `` | `MUL` | `` |  |
| `mission_data_json` | `json` | YES | `` | `` | `` |  |
| `status` | `varchar(50)` | YES | `active` | `MUL` | `` |  |
| `assigned_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `completed_at` | `datetime` | YES | `` | `` | `` |  |

Indexes:
- `idx_character` (INDEX, BTREE): `character_name`
- `idx_status` (INDEX, BTREE): `status`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `player_characters`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `name` | `varchar(255)` | NO | `` | `UNI` | `` |  |
| `class_name` | `varchar(255)` | YES | `` | `` | `` |  |
| `species` | `varchar(500)` | YES | `` | `` | `` |  |
| `player_name` | `varchar(255)` | YES | `` | `` | `` |  |
| `player_discord_id` | `varchar(50)` | YES | `` | `MUL` | `` |  |
| `profile_json` | `json` | YES | `` | `` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |
| `oracle_notes` | `text` | YES | `` | `` | `` |  |
| `raw_block` | `text` | YES | `` | `` | `` |  |
| `race` | `varchar(500)` | YES | `` | `` | `VIRTUAL GENERATED` |  |

Indexes:
- `idx_player` (INDEX, BTREE): `player_discord_id`
- `name` (UNIQUE, BTREE): `name`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `player_listings`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `player_id` | `varchar(100)` | YES | `` | `MUL` | `` |  |
| `player_name` | `varchar(255)` | YES | `` | `` | `` |  |
| `item_name` | `varchar(255)` | NO | `` | `` | `` |  |
| `asking_price` | `int` | YES | `` | `` | `` |  |
| `status` | `varchar(50)` | YES | `active` | `MUL` | `` |  |
| `created_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |
| `listing_json` | `json` | YES | `` | `` | `` |  |
| `buy_now_price` | `bigint` | YES | `` | `` | `` |  |
| `highest_bidder_id` | `bigint` | YES | `` | `` | `` |  |
| `highest_bidder_name` | `varchar(100)` | YES | `` | `` | `` |  |
| `proxy_max` | `bigint` | YES | `` | `` | `` |  |

Indexes:
- `idx_player` (INDEX, BTREE): `player_id`
- `idx_status` (INDEX, BTREE): `status`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `resurrection_queue`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `npc_name` | `varchar(255)` | NO | `` | `` | `` |  |
| `died_at` | `datetime` | YES | `` | `` | `` |  |
| `resurrect_at` | `datetime` | YES | `` | `MUL` | `` |  |
| `status` | `varchar(50)` | YES | `pending` | `` | `` |  |

Indexes:
- `idx_resurrect` (INDEX, BTREE): `resurrect_at`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `rift_state`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `active` | `tinyint(1)` | YES | `0` | `` | `` |  |
| `intensity` | `int` | YES | `0` | `` | `` |  |
| `location` | `varchar(255)` | YES | `` | `` | `` |  |
| `effects_json` | `json` | YES | `` | `` | `` |  |
| `started_at` | `datetime` | YES | `` | `` | `` |  |
| `ended_at` | `datetime` | YES | `` | `` | `` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`

### `skills`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `filename` | `varchar(500)` | NO | `` | `UNI` | `` |  |
| `title` | `varchar(500)` | YES | `` | `` | `` |  |
| `keywords` | `text` | YES | `` | `` | `` |  |
| `category` | `varchar(100)` | YES | `` | `` | `` |  |
| `version` | `int` | YES | `1` | `` | `` |  |
| `source` | `varchar(100)` | YES | `` | `` | `` |  |
| `body` | `longtext` | YES | `` | `` | `` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |

Indexes:
- `filename` (UNIQUE, BTREE): `filename`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `tia_market`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `sector_name` | `varchar(100)` | YES | `` | `` | `` |  |
| `value_json` | `json` | YES | `` | `` | `` |  |
| `state_json` | `json` | YES | `` | `` | `` |  |
| `sector` | `varchar(100)` | NO | `` | `UNI` | `` |  |
| `value` | `double` | YES | `` | `` | `` |  |
| `trend` | `text` | YES | `` | `` | `` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |
| `last_updated` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |
| `prev_value` | `double` | YES | `` | `` | `` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`
- `sector` (UNIQUE, BTREE): `sector`

### `towerbay_auctions`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `item_name` | `varchar(255)` | NO | `` | `` | `` |  |
| `seller_id` | `varchar(100)` | YES | `` | `` | `` |  |
| `seller_name` | `varchar(255)` | YES | `` | `` | `` |  |
| `current_bid` | `int` | YES | `0` | `` | `` |  |
| `buy_now_price` | `int` | YES | `` | `` | `` |  |
| `expires_at` | `datetime` | YES | `` | `MUL` | `` |  |
| `status` | `varchar(50)` | YES | `active` | `MUL` | `` |  |
| `auction_json` | `json` | YES | `` | `` | `` |  |
| `winner_id` | `varchar(100)` | YES | `` | `` | `` |  |
| `highest_bidder_id` | `bigint` | YES | `` | `` | `` |  |
| `highest_bidder_name` | `varchar(100)` | YES | `` | `` | `` |  |
| `proxy_max` | `bigint` | YES | `` | `` | `` |  |

Indexes:
- `idx_expires` (INDEX, BTREE): `expires_at`
- `idx_status` (INDEX, BTREE): `status`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `towerbay_bids`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `listing_id` | `varchar(50)` | NO | `` | `MUL` | `` |  |
| `listing_type` | `enum('ai','player')` | NO | `ai` | `` | `` |  |
| `bidder_id` | `bigint` | NO | `` | `MUL` | `` |  |
| `bidder_name` | `varchar(100)` | NO | `` | `` | `` |  |
| `amount` | `bigint` | NO | `` | `` | `` |  |
| `proxy_max` | `bigint` | YES | `` | `` | `` |  |
| `successful` | `tinyint(1)` | NO | `1` | `` | `` |  |
| `bid_at` | `datetime` | NO | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |

Indexes:
- `idx_bidder` (INDEX, BTREE): `bidder_id`
- `idx_listing` (INDEX, BTREE): `listing_id`, `listing_type`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `training_docs`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `filename` | `varchar(500)` | NO | `` | `UNI` | `` |  |
| `doc_type` | `varchar(50)` | YES | `` | `` | `` |  |
| `content` | `longtext` | YES | `` | `` | `` |  |
| `char_count` | `int` | YES | `` | `` | `` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED` |  |

Indexes:
- `filename` (UNIQUE, BTREE): `filename`
- `PRIMARY` (PRIMARY, BTREE): `id`

### `weather_state`

| Column | Type | Null | Default | Key | Extra | Comment |
|---|---|---:|---|---|---|---|
| `id` | `int` | NO | `` | `PRI` | `auto_increment` |  |
| `current_weather` | `varchar(100)` | YES | `` | `` | `` |  |
| `temperature` | `varchar(50)` | YES | `` | `` | `` |  |
| `effects_json` | `json` | YES | `` | `` | `` |  |
| `updated_at` | `datetime` | YES | `CURRENT_TIMESTAMP` | `` | `DEFAULT_GENERATED on update CURRENT_TIMESTAMP` |  |

Indexes:
- `PRIMARY` (PRIMARY, BTREE): `id`
