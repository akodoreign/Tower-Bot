# Schema

### character_snapshots
- id: int auto_increment (pk)
- char_id: bigint (required, fk)
- char_name: varchar (required)
- player: varchar
- snapshot_json: json
- fetched_at: datetime (default)
- fetched_at: desc

### npcs
- id: int auto_increment (pk)
- name: varchar (unique)
- faction: varchar
- role: varchar
- location: varchar
- description: text
- arrival_date: datetime
- appearance_json: json

### missions
- id: int auto_increment (pk)
- title: varchar (required)
- description: text
- difficulty: varchar
- faction: varchar
- npc_giver: varchar
- reward_ec: integer (default)
- expires_at: datetime
- claimed_by: varchar
- completed_at: datetime
- message_id: varchar (fk)

### bounties
- id: int auto_increment (pk)
- title: varchar (required)
- target_type: varchar
- target_name: varchar
- reward_ec: integer (default)
- status: varchar (default)
- claimed_by: varchar

### news_entries
- id: int auto_increment (pk)
- headline: varchar (required)
- body: text
- category: varchar
- posted_at: datetime (default)
- news_type: varchar
- message_id: varchar (fk)

### player_characters
- id: int auto_increment (pk)
- name: varchar (unique)
- class_name: varchar
- species: varchar
- player_name: varchar
- player_discord_id: varchar (fk)
- profile_json: json

### faction_reputation
- id: int auto_increment (pk)
- faction_name: varchar (unique)
- reputation_score: integer (default)
- tier: varchar
- last_updated: datetime (pk, default)
- current_weather: varchar
- temperature: varchar
- effects_json: json
- ec_to_kharma_rate: decimal(10
- trend: varchar
- season_number: integer
- champions_json: json
- standings_json: json
- started_at: datetime
- faction: varchar
- event_type: varchar
- event_date: datetime
- description: text

### missing_persons
- id: int auto_increment (pk)
- person_name: varchar (required)
- last_seen_location: varchar
- reported_at: datetime (default)
- status: varchar (default)
- found_at: datetime

### rift_state
- id: int auto_increment (pk)
- active: boolean (default)
- intensity: integer (default)
- location: varchar
- effects_json: json
- started_at: datetime
- sector: varchar (unique)
- value: decimal(10
- trend: varchar
- item_name: varchar (required)
- seller_id: varchar (fk)
- seller_name: varchar
- current_bid: integer (default)
- buy_now_price: integer
- expires_at: datetime
- status: varchar (default)
- winner_id: varchar (fk)

### player_listings
- id: int auto_increment (pk)
- player_id: varchar (fk)
- player_name: varchar
- item_name: varchar (required)
- asking_price: integer
- status: varchar (default)

### npc_appearances
- id: int auto_increment (pk)
- npc_name: varchar (unique)
- appearance_prompt: text
- style: varchar
- generated_at: datetime (pk, default)
- party_name: varchar (unique)
- members_json: json
- reputation: integer (default)
- formed_at: datetime (default)
- status: varchar (pk, default)
- entity_type: varchar (required)
- entity_name: varchar (required)
- image_path: varchar
- ref_count: integer (default)

### personal_missions
- id: int auto_increment (pk)
- character_name: varchar (required)
- mission_data_json: json
- status: varchar (default)
- assigned_at: datetime (default)
- completed_at: datetime

### resurrection_queue
- id: int auto_increment (pk)
- npc_name: varchar (required)
- died_at: datetime
- resurrect_at: datetime
- status: varchar (default)

### news_types
- id: int auto_increment (pk)
- type_name: varchar (unique)
- template: text
- weight: decimal(5
- usage_count: integer (default)

### mission_types
- id: int auto_increment (pk)
- type_name: varchar (unique)
- template: text
- difficulty_range: varchar
- usage_count: integer (pk, default)
- event_type: varchar (required)
- npc_name: varchar
- event_data_json: json
- occurred_at: datetime (default)
