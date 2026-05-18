# Project Context

This is a python project using raw-http.

The database has 15 models. See .codesight/schema.md for the full schema with fields, types, and relations.
Middleware includes: custom.

High-impact files (most imported, changes here affect many other files):
- /layouts.py (imported by 5 files)
- /schemas.py (imported by 5 files)
- /base.py (imported by 3 files)
- /mission_json_builder.py (imported by 2 files)
- /encounters.py (imported by 2 files)
- /locations.py (imported by 2 files)
- /docx.py (imported by 1 files)
- /pptx.py (imported by 1 files)

Required environment variables (no defaults):
- DDB_COBALT_TOKEN (src\character_monitor.py)
- DISCORD_BOT_TOKEN (.env.example)
- DISCORD_CHANNEL_ID (.env.example)
- LEARN_HOUR_END (src\self_learning.py)
- LEARN_HOUR_START (src\self_learning.py)
- MAPS_CHANNEL_ID (src\mission_builder\maps.py)
- MYSQL_DB (sql_refactor_setup.py)
- MYSQL_HOST (sql_refactor_setup.py)
- MYSQL_PASSWORD (sql_refactor_setup.py)
- MYSQL_USER (sql_refactor_setup.py)
- OPENAI_ENABLED (src\art.py)
- REPLYING_ALL_DISCORD_CHANNEL_ID (.env.example)

Read .codesight/wiki/index.md for orientation (WHERE things live). Then read actual source files before implementing. Wiki articles are navigation aids, not implementation guides.
Read .codesight/CODESIGHT.md for the complete AI context map including all routes, schema, components, libraries, config, middleware, and dependency graph.
