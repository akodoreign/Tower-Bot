-- Add character_snapshots table for DDB character monitor
-- Run with: mysql -u Claude -p tower_bot < alter_add_character_snapshots.sql

CREATE TABLE IF NOT EXISTS character_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    char_id BIGINT NOT NULL,
    char_name VARCHAR(255) NOT NULL,
    player VARCHAR(100),
    snapshot_json JSON,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_char_id (char_id),
    INDEX idx_fetched (fetched_at DESC),
    INDEX idx_char_fetched (char_id, fetched_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE OR REPLACE VIEW latest_character_snapshots AS
SELECT cs.*
FROM character_snapshots cs
INNER JOIN (
    SELECT char_id, MAX(fetched_at) as max_fetched
    FROM character_snapshots
    GROUP BY char_id
) latest ON cs.char_id = latest.char_id AND cs.fetched_at = latest.max_fetched;
