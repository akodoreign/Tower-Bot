# Dependency Graph

## Most Imported Files (change these carefully)

- `/layouts.py` — imported by **5** files
- `/schemas.py` — imported by **5** files
- `/base.py` — imported by **3** files
- `/mission_json_builder.py` — imported by **2** files
- `/encounters.py` — imported by **2** files
- `/locations.py` — imported by **2** files
- `/docx.py` — imported by **1** files
- `/pptx.py` — imported by **1** files
- `/redlining.py` — imported by **1** files
- `/room_generator.py` — imported by **1** files
- `/tile_generator.py` — imported by **1** files
- `/stitcher.py` — imported by **1** files
- `/json_generator.py` — imported by **1** files
- `/image_generator.py` — imported by **1** files
- `/api.py` — imported by **1** files
- `/mission_types.py` — imported by **1** files
- `/leads.py` — imported by **1** files
- `/npcs.py` — imported by **1** files
- `/rewards.py` — imported by **1** files
- `/docx_builder.py` — imported by **1** files

## Import Map (who imports what)

- `/layouts.py` ← `src\mission_builder\dungeon_delve\docx_formatter.py`, `src\mission_builder\dungeon_delve\room_generator.py`, `src\mission_builder\dungeon_delve\stitcher.py`, `src\mission_builder\dungeon_delve\tile_generator.py`, `src\mission_builder\dungeon_delve\__init__.py`
- `/schemas.py` ← `src\mission_builder\image_generator.py`, `src\mission_builder\image_integration.py`, `src\mission_builder\json_generator.py`, `src\mission_builder\mission_json_builder.py`, `src\mission_builder\__init__.py`
- `/base.py` ← `skills\docx\scripts\office\validators\docx.py`, `skills\docx\scripts\office\validators\pptx.py`, `skills\docx\scripts\office\validators\__init__.py`
- `/mission_json_builder.py` ← `src\mission_builder\json_generator.py`, `src\mission_builder\__init__.py`
- `/encounters.py` ← `src\mission_builder\json_generator.py`, `src\mission_builder\__init__.py`
- `/locations.py` ← `src\mission_builder\leads.py`, `src\mission_builder\__init__.py`
- `/docx.py` ← `skills\docx\scripts\office\validators\__init__.py`
- `/pptx.py` ← `skills\docx\scripts\office\validators\__init__.py`
- `/redlining.py` ← `skills\docx\scripts\office\validators\__init__.py`
- `/room_generator.py` ← `src\mission_builder\dungeon_delve\__init__.py`
