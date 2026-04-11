# Database

> **Navigation aid.** Schema shapes and field types extracted via AST. Read the actual schema source files before writing migrations or query logic.

**unknown** — 15 models

### character_snapshots

pk: `id` (int auto_increment) · fk: char_id

- `id`: int auto_increment _(pk)_
- `char_id`: bigint _(required, fk)_
- `char_name`: varchar _(required)_
- `player`: varchar
- `snapshot_json`: json
- `fetched_at`: datetime _(default)_
- `fetched_at`: desc

### npcs

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `name`: varchar _(unique)_
- `faction`: varchar
- `role`: varchar
- `location`: varchar
- `description`: text
- `arrival_date`: datetime
- `appearance_json`: json

### missions

pk: `id` (int auto_increment) · fk: message_id

- `id`: int auto_increment _(pk)_
- `title`: varchar _(required)_
- `description`: text
- `difficulty`: varchar
- `faction`: varchar
- `npc_giver`: varchar
- `reward_ec`: integer _(default)_
- `expires_at`: datetime
- `claimed_by`: varchar
- `completed_at`: datetime
- `message_id`: varchar _(fk)_

### bounties

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `title`: varchar _(required)_
- `target_type`: varchar
- `target_name`: varchar
- `reward_ec`: integer _(default)_
- `status`: varchar _(default)_
- `claimed_by`: varchar

### news_entries

pk: `id` (int auto_increment) · fk: message_id

- `id`: int auto_increment _(pk)_
- `headline`: varchar _(required)_
- `body`: text
- `category`: varchar
- `posted_at`: datetime _(default)_
- `news_type`: varchar
- `message_id`: varchar _(fk)_

### player_characters

pk: `id` (int auto_increment) · fk: player_discord_id

- `id`: int auto_increment _(pk)_
- `name`: varchar _(unique)_
- `class_name`: varchar
- `species`: varchar
- `player_name`: varchar
- `player_discord_id`: varchar _(fk)_
- `profile_json`: json

### faction_reputation

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `faction_name`: varchar _(unique)_
- `reputation_score`: integer _(default)_
- `tier`: varchar
- `last_updated`: datetime _(pk, default)_
- `current_weather`: varchar
- `temperature`: varchar
- `effects_json`: json
- `ec_to_kharma_rate`: decimal(10
- `trend`: varchar
- `season_number`: integer
- `champions_json`: json
- `standings_json`: json
- `started_at`: datetime
- `faction`: varchar
- `event_type`: varchar
- `event_date`: datetime
- `description`: text

### missing_persons

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `person_name`: varchar _(required)_
- `last_seen_location`: varchar
- `reported_at`: datetime _(default)_
- `status`: varchar _(default)_
- `found_at`: datetime

### rift_state

pk: `id` (int auto_increment) · fk: seller_id, winner_id

- `id`: int auto_increment _(pk)_
- `active`: boolean _(default)_
- `intensity`: integer _(default)_
- `location`: varchar
- `effects_json`: json
- `started_at`: datetime
- `sector`: varchar _(unique)_
- `value`: decimal(10
- `trend`: varchar
- `item_name`: varchar _(required)_
- `seller_id`: varchar _(fk)_
- `seller_name`: varchar
- `current_bid`: integer _(default)_
- `buy_now_price`: integer
- `expires_at`: datetime
- `status`: varchar _(default)_
- `winner_id`: varchar _(fk)_

### player_listings

pk: `id` (int auto_increment) · fk: player_id

- `id`: int auto_increment _(pk)_
- `player_id`: varchar _(fk)_
- `player_name`: varchar
- `item_name`: varchar _(required)_
- `asking_price`: integer
- `status`: varchar _(default)_

### npc_appearances

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `npc_name`: varchar _(unique)_
- `appearance_prompt`: text
- `style`: varchar
- `generated_at`: datetime _(pk, default)_
- `party_name`: varchar _(unique)_
- `members_json`: json
- `reputation`: integer _(default)_
- `formed_at`: datetime _(default)_
- `status`: varchar _(pk, default)_
- `entity_type`: varchar _(required)_
- `entity_name`: varchar _(required)_
- `image_path`: varchar
- `ref_count`: integer _(default)_

### personal_missions

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `character_name`: varchar _(required)_
- `mission_data_json`: json
- `status`: varchar _(default)_
- `assigned_at`: datetime _(default)_
- `completed_at`: datetime

### resurrection_queue

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `npc_name`: varchar _(required)_
- `died_at`: datetime
- `resurrect_at`: datetime
- `status`: varchar _(default)_

### news_types

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `type_name`: varchar _(unique)_
- `template`: text
- `weight`: decimal(5
- `usage_count`: integer _(default)_

### mission_types

pk: `id` (int auto_increment)

- `id`: int auto_increment _(pk)_
- `type_name`: varchar _(unique)_
- `template`: text
- `difficulty_range`: varchar
- `usage_count`: integer _(pk, default)_
- `event_type`: varchar _(required)_
- `npc_name`: varchar
- `event_data_json`: json
- `occurred_at`: datetime _(default)_

## Schema Source Files

Read and edit these files when adding columns, creating migrations, or changing relations:

- `/schemas.py` — imported by **5** files

---
_Back to [overview.md](./overview.md)_