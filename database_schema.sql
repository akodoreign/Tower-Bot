USE tower_bot;

-- NPCs table
CREATE TABLE IF NOT EXISTS npcs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    faction VARCHAR(100),
    role VARCHAR(100),
    location VARCHAR(255),
    description TEXT,
    arrival_date DATETIME,
    status ENUM('alive','dead','missing') DEFAULT 'alive',
    appearance_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_faction(faction),
    INDEX idx_status(status),
    INDEX idx_location(location)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Missions table
CREATE TABLE IF NOT EXISTS missions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    difficulty VARCHAR(50),
    faction VARCHAR(100),
    npc_giver VARCHAR(255),
    status ENUM('active','claimed','completed','expired','failed') DEFAULT 'active',
    reward_ec INT DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME,
    claimed_by VARCHAR(255),
    completed_at DATETIME,
    message_id VARCHAR(50),
    INDEX idx_status(status),
    INDEX idx_faction(faction)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Bounties table
CREATE TABLE IF NOT EXISTS bounties (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    target_type VARCHAR(50),
    target_name VARCHAR(255),
    reward_ec INT DEFAULT 0,
    status VARCHAR(50) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    claimed_by VARCHAR(255),
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- News entries table
CREATE TABLE IF NOT EXISTS news_entries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    headline VARCHAR(500) NOT NULL,
    body TEXT,
    category VARCHAR(100),
    posted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    news_type VARCHAR(100),
    message_id VARCHAR(50),
    INDEX idx_posted(posted_at DESC),
    INDEX idx_category(category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Player characters table
CREATE TABLE IF NOT EXISTS player_characters (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    class_name VARCHAR(100),
    species VARCHAR(100),
    player_name VARCHAR(255),
    player_discord_id VARCHAR(50),
    profile_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_player(player_discord_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Faction reputation table
CREATE TABLE IF NOT EXISTS faction_reputation (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faction_name VARCHAR(100) UNIQUE NOT NULL,
    reputation_score INT DEFAULT 0,
    tier VARCHAR(50),
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Weather state table
CREATE TABLE IF NOT EXISTS weather_state (
    id INT AUTO_INCREMENT PRIMARY KEY,
    current_weather VARCHAR(100),
    temperature VARCHAR(50),
    effects_json JSON,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Economy state table
CREATE TABLE IF NOT EXISTS economy_state (
    id INT AUTO_INCREMENT PRIMARY KEY,
    ec_to_kharma_rate DECIMAL(10,4) DEFAULT 1.0,
    trend VARCHAR(50),
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Arena seasons table
CREATE TABLE IF NOT EXISTS arena_seasons (
    id INT AUTO_INCREMENT PRIMARY KEY,
    season_number INT,
    champions_json JSON,
    standings_json JSON,
    started_at DATETIME,
    ended_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Faction events table
CREATE TABLE IF NOT EXISTS faction_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    faction VARCHAR(100),
    event_type VARCHAR(100),
    event_date DATETIME,
    description TEXT,
    INDEX idx_date(event_date),
    INDEX idx_faction(faction)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Missing persons table
CREATE TABLE IF NOT EXISTS missing_persons (
    id INT AUTO_INCREMENT PRIMARY KEY,
    person_name VARCHAR(255) NOT NULL,
    last_seen_location VARCHAR(255),
    reported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'missing',
    found_at DATETIME,
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Rift state table
CREATE TABLE IF NOT EXISTS rift_state (
    id INT AUTO_INCREMENT PRIMARY KEY,
    active BOOLEAN DEFAULT FALSE,
    intensity INT DEFAULT 0,
    location VARCHAR(255),
    effects_json JSON,
    started_at DATETIME,
    ended_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TIA market table
CREATE TABLE IF NOT EXISTS tia_market (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sector VARCHAR(100) UNIQUE NOT NULL,
    value DECIMAL(10,2) DEFAULT 100.00,
    trend VARCHAR(50),
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- TowerBay auctions table
CREATE TABLE IF NOT EXISTS towerbay_auctions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    item_name VARCHAR(255) NOT NULL,
    seller_id VARCHAR(100),
    seller_name VARCHAR(255),
    current_bid INT DEFAULT 0,
    buy_now_price INT,
    expires_at DATETIME,
    status VARCHAR(50) DEFAULT 'active',
    winner_id VARCHAR(100),
    INDEX idx_status(status),
    INDEX idx_expires(expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Player listings table
CREATE TABLE IF NOT EXISTS player_listings (
    id INT AUTO_INCREMENT PRIMARY KEY,
    player_id VARCHAR(100),
    player_name VARCHAR(255),
    item_name VARCHAR(255) NOT NULL,
    asking_price INT,
    status VARCHAR(50) DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_status(status),
    INDEX idx_player(player_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- NPC appearances table
CREATE TABLE IF NOT EXISTS npc_appearances (
    id INT AUTO_INCREMENT PRIMARY KEY,
    npc_name VARCHAR(255) UNIQUE NOT NULL,
    appearance_prompt TEXT,
    style VARCHAR(50),
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Party profiles table
CREATE TABLE IF NOT EXISTS party_profiles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    party_name VARCHAR(255) UNIQUE NOT NULL,
    members_json JSON,
    reputation INT DEFAULT 0,
    formed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'active'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Image refs table
CREATE TABLE IF NOT EXISTS image_refs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    entity_type VARCHAR(50) NOT NULL,
    entity_name VARCHAR(255) NOT NULL,
    image_path VARCHAR(500),
    ref_count INT DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY unique_entity(entity_type, entity_name),
    INDEX idx_entity(entity_type, entity_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Personal missions table
CREATE TABLE IF NOT EXISTS personal_missions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    character_name VARCHAR(255) NOT NULL,
    mission_data_json JSON,
    status VARCHAR(50) DEFAULT 'active',
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    INDEX idx_character(character_name),
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Resurrection queue table
CREATE TABLE IF NOT EXISTS resurrection_queue (
    id INT AUTO_INCREMENT PRIMARY KEY,
    npc_name VARCHAR(255) NOT NULL,
    died_at DATETIME,
    resurrect_at DATETIME,
    status VARCHAR(50) DEFAULT 'pending',
    INDEX idx_resurrect(resurrect_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- News types table (self-learning)
CREATE TABLE IF NOT EXISTS news_types (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type_name VARCHAR(100) UNIQUE NOT NULL,
    template TEXT,
    weight DECIMAL(5,2) DEFAULT 1.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    usage_count INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Mission types table (self-learning)
CREATE TABLE IF NOT EXISTS mission_types (
    id INT AUTO_INCREMENT PRIMARY KEY,
    type_name VARCHAR(100) UNIQUE NOT NULL,
    template TEXT,
    difficulty_range VARCHAR(50),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    usage_count INT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Lifecycle events table
CREATE TABLE IF NOT EXISTS lifecycle_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    npc_name VARCHAR(255),
    event_data_json JSON,
    occurred_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_occurred(occurred_at DESC),
    INDEX idx_type(event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Insert default weather state
INSERT INTO weather_state (current_weather, temperature, effects_json) 
VALUES ('clear', 'moderate', '{}')
ON DUPLICATE KEY UPDATE id=id;

-- Insert default economy state
INSERT INTO economy_state (ec_to_kharma_rate, trend)
VALUES (1.0, 'stable')
ON DUPLICATE KEY UPDATE id=id;

-- Insert default rift state
INSERT INTO rift_state (active, intensity, location, effects_json)
VALUES (FALSE, 0, NULL, '{}')
ON DUPLICATE KEY UPDATE id=id;
