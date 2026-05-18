-- Seed faction descriptions from hardcoded _WORLD_LORE into faction_reputation
INSERT INTO faction_reputation (faction_name, reputation_score, tier, leader, location_name, description, motto)
VALUES
  ('Iron Fang Consortium',  2,  'Disliked', 'Guildmaster Serrik Dhal', 'Markets Infinite',  'Relic and smuggling cartel.',           'Profit is virtue.')
, ('Argent Blades',         0,  'Friendly', 'Lady Cerys Valemont',     'Guild Spires',      'Glory adventurer guild. Arena duels, Rift showcases.', 'Fame is currency.')
, ('Wardens of Ash',        0,  'Liked',    'Captain Havel Korin',     'Outer Wall',        'City defenders.',                       'Hold the Line.')
, ('Serpent Choir',        -1,  'Disliked', 'High Apostle Yzura',      'Sanctum Quarter',   'Divine contract brokers.',              'Every miracle has a clause.')
, ('Obsidian Lotus',       -2,  'Neutral',  'The Widow',               'The Warrens',       'Black-market syndicate. Memory erasure, bottled souls, god-tongue ink.', NULL)
, ('Glass Sigil',           0,  'Liked',    'Senior Archivist Pell',   NULL,                'Arcane archivists. Tracks Rift residue anomalies.', NULL)
, ('Patchwork Saints',      1,  'Friendly', NULL,                      'The Warrens',       'Failed adventurers protecting Warrens residents. Minimal resources, pure principle.', NULL)
, ('Adventurers Guild',     1,  'Friendly', 'Mari Fen (front desk)',   NULL,                'Quest hub, Rift assignments.',          NULL)
, ('Guild of Ashen Scrolls',0,  'Neutral',  'Archivist Eir Velan',     'Grand Forum Library','Fate archivists sworn to Thesaurus.',  NULL)
, ('Tower Authority',       0,  'Neutral',  'Director Myra Kess',      NULL,                'External oversight body. Treats adventurers as data points.', NULL)
, ('Wizards Tower',         0,  'Partner',  'Archmage Yaulderna Silverstreak', NULL,        'Arcane academy and research institution. Knowledge preservation, responsible magic use, arcane licensing.', NULL)
ON DUPLICATE KEY UPDATE
  leader        = VALUES(leader),
  location_name = VALUES(location_name),
  description   = VALUES(description),
  motto         = VALUES(motto);

-- Seed static world lore (setting, currency, gods) into global_state
INSERT INTO global_state (state_key, state_value) VALUES
('world_setting', JSON_OBJECT(
  'overview',  'The Undercity — a sealed city under a Dome, built around the Tower of Last Chance.',
  'rifts',     'Rifts are rare tears in reality that spawn monsters and warp physics. They are feared events, not routine occurrences.',
  'adventurers','Adventurers are a recognised economic class: ranked, taxed, tracked, and occasionally harvested by gods.'
)),
('world_currency', JSON_OBJECT(
  'EC',     'Essence Coins — everyday money.',
  'Kharma', 'Crystallised faith, traded and stolen.',
  'LP',     'Legend Points — heroic fame. High LP attracts divine attention and the Culinary Council''s hunger.'
)),
('world_gods', JSON_ARRAY(
  JSON_OBJECT('name','Culinary Council',      'description','Predator deities harvesting heroic souls. Members: Gourmand Prime the Bone King, Mother Mire, The Hollow Waiter.'),
  JSON_OBJECT('name','Thesaurus',             'description','Archives all legends. Wants the perfect heroic story.'),
  JSON_OBJECT('name','Ashara the Phoenix Marshal','description','War/fire god. Wardens'' secret patron. Opposes the Culinary Council.'),
  JSON_OBJECT('name','Veha the Silent Bloom', 'description','God of forgetting. Obsidian Lotus patron.')
)),
('world_key_npcs', JSON_ARRAY(
  'Mara the Scrapper (Scrapworks boss)',
  'Brother Thane (cult leader, building something in the Warrens)',
  'Sable (Night Pits boss)',
  'Aric Veyne (SS-Rank adventurer, Silver Spire)',
  'Magister Liora (FTA Tower liaison)',
  'Kessan & Mira (Grand Forum info brokers, twins)',
  'Elune (apothecary owner)',
  'Kiva (Hermes shrine scout)',
  'Wex (courier, currently in trouble)',
  'Dova (Glass Sigil junior archivist)',
  'Lieutenant Varen (Wardens)'
)),
('world_active_tensions', JSON_ARRAY(
  'Brother Thane is recruiting aggressively near the Collapsed Plaza. The Saints and Wardens are both watching.',
  'Serpent Choir internal corruption: financial officer Sevas went missing with a tithe ledger implicating Brother Enn.',
  'Obsidian Lotus memory-erasure contracts are under FTA scrutiny.',
  'An independent researcher named Elara Mound has been secretly harvesting a stable Rift seam outside the city.'
))
ON DUPLICATE KEY UPDATE state_value = VALUES(state_value);
