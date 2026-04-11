"""One-time script: populate bot_commands table with all slash commands."""
import mysql.connector, json

conn = mysql.connector.connect(
    host='localhost', user='Claude', password='WXdCPJmeDfaQALaktzF6!', database='tower_bot'
)
cur = conn.cursor()

commands = [
    # (command_name, description, source_file, source_function, cog_name, dm_only, parameters, notes)
    ('ask',              'Chat with the AI (replies in same channel)',               'src/cogs/chat.py',        'ask',              'chat',     0, [{'name':'message','type':'str','required':True}],  ''),
    ('chat',             'Open a private DM thread with the AI',                    'src/cogs/chat.py',        'chat',             'chat',     0, [{'name':'message','type':'str','required':True}],  ''),
    ('drawcard',         'Draw a tarot card for a character',                       'src/cogs/chat.py',        'drawcard',         'chat',     0, [{'name':'character','type':'str','required':False}], ''),
    ('image',            'Generate an image via Stable Diffusion',                  'src/cogs/image.py',       'image',            'image',    0, [{'name':'prompt','type':'str','required':True}],   ''),
    ('generatenpcs',     'Generate N new NPCs for the Undercity roster',            'src/bot.py',              'generatenpcs',     'bot',      0, [{'name':'count','type':'int','required':False,'default':3}], 'DM preferred'),
    ('npcprofile',       'Show full profile for a named NPC',                       'src/bot.py',              'npcprofile',       'bot',      0, [{'name':'name','type':'str','required':True}],     ''),
    ('lifecycle',        'Manually trigger the NPC daily lifecycle',                'src/bot.py',              'lifecycle',        'bot',      1, [], 'DM only'),
    ('resolvemission',   'Mark a claimed mission complete or failed',               'src/cogs/missions.py',    'resolvemission',   'missions', 1, [{'name':'title','type':'str','required':True},{'name':'outcome','type':'choice','choices':['complete','fail'],'required':True}], 'DM only'),
    ('missionboard',     'Post active missions to the mission board channel',       'src/bot.py',              'missionboard',     'bot',      0, [], ''),
    ('dailybrief',       'Post the daily news bulletin immediately',                'src/bot.py',              'dailybrief',       'bot',      0, [], ''),
    ('weather',          'Show current Dome weather',                               'src/bot.py',              'weather',          'bot',      0, [], ''),
    ('exchange',         'Show current EC/Kharma exchange rate',                    'src/bot.py',              'exchange',         'bot',      0, [], ''),
    ('bountyboard',      'Show active bounties on the bounty board',                'src/bot.py',              'bountyboard',      'bot',      0, [], ''),
    ('addgold',          'Add gold/EC to a player character',                       'src/bot.py',              'addgold',          'bot',      1, [{'name':'character','type':'str','required':True},{'name':'amount','type':'int','required':True}], 'DM only'),
    ('spendgold',        'Deduct gold/EC from a player character',                  'src/bot.py',              'spendgold',        'bot',      1, [{'name':'character','type':'str','required':True},{'name':'amount','type':'int','required':True}], 'DM only'),
    ('towerbay',         'Show current Tower Bay auction listings',                 'src/bot.py',              'towerbay',         'bot',      0, [], ''),
    ('arenaseason',      'Show current arena season standings',                     'src/bot.py',              'arenaseason',      'bot',      0, [], ''),
    ('factionrep',       'Show faction reputation standings',                       'src/bot.py',              'factionrep',       'bot',      0, [], ''),
    ('rift',             'Show current rift state',                                 'src/bot.py',              'rift',             'bot',      0, [], ''),
    ('character',        'Look up a DDB character sheet by ID',                     'src/bot.py',              'character',        'bot',      0, [{'name':'character_id','type':'str','required':True}], ''),
    ('sync',             'Force sync slash commands to Discord',                    'src/bot.py',              'sync',             'bot',      1, [], 'DM only'),
    ('spell',            'Look up a spell from the SRD',                            'src/bot.py',              'spell',            'bot',      0, [{'name':'spell_name','type':'str','required':True}], ''),
    ('style',            'Generate a writing style sample',                         'src/bot.py',              'style',            'bot',      0, [{'name':'genre','type':'str','required':False}], ''),
    ('learn',            'Manually trigger the self-learning cycle',                'src/bot.py',              'learn',            'bot',      1, [], 'DM only'),
    ('missingpersons',   'Show current missing persons board',                      'src/bot.py',              'missingpersons',   'bot',      0, [], ''),
    ('personalmission',  'Show or claim a personal mission',                        'src/bot.py',              'personalmission',  'bot',      0, [{'name':'action','type':'str','required':False}], ''),
    ('resurrect',        'Attempt to resurrect a dead NPC (adds to queue)',         'src/bot.py',              'resurrect',        'bot',      0, [{'name':'npc_name','type':'str','required':True}], ''),
    ('tia',              'Consult TIA the market oracle',                           'src/bot.py',              'tia',              'bot',      0, [{'name':'query','type':'str','required':True}], ''),
    ('npcmap',           'Post NPC appearance reference image to maps channel',     'src/bot.py',              'npcmap',           'bot',      0, [{'name':'npc_name','type':'str','required':True}], ''),
    ('lore',             'Query the lore/RAG system',                               'src/bot.py',              'lore',             'bot',      0, [{'name':'query','type':'str','required':True}], ''),
]

for row in commands:
    name, desc, src_file, src_fn, cog, dm_only, params, notes = row
    cur.execute(
        """INSERT INTO bot_commands
               (command_name, description, source_file, source_function, cog_name, dm_only, parameters, notes)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           ON DUPLICATE KEY UPDATE
             description=VALUES(description), source_file=VALUES(source_file),
             source_function=VALUES(source_function), cog_name=VALUES(cog_name),
             dm_only=VALUES(dm_only), parameters=VALUES(parameters), notes=VALUES(notes),
             updated_at=NOW()""",
        (name, desc, src_file, src_fn, cog, dm_only, json.dumps(params), notes)
    )

conn.commit()
cur.execute('SELECT COUNT(*) FROM bot_commands')
print('Commands in bot_commands table:', cur.fetchone()[0])
cur.close()
conn.close()
