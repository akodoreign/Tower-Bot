# fix_mistral_to_qwen.py
import os

ROOT = r"C:\Users\akodoreign\Desktop\chatGPT-discord-bot"
NEW_MODEL = "qwen3-8b-slim:latest"

# Model strings to replace (exact matches)
REPLACEMENTS = [
    ('"mistral:latest"', f'"{NEW_MODEL}"'),
    ("'mistral:latest'", f"'{NEW_MODEL}'"),
    ('"mistral-nemo:latest"', f'"{NEW_MODEL}"'),
    ("'mistral-nemo:latest'", f"'{NEW_MODEL}'"),
    ('"mistral"', f'"{NEW_MODEL}"'),
    ("'mistral'", f"'{NEW_MODEL}'"),
]

FILES_TO_FIX = [
    r"src\news_feed.py",
    r"src\aclient.py",
    r"src\mission_compiler.py",
    r"src\npc_appearance.py",
    r"src\npc_lifecycle.py",
    r"src\party_profiles.py",
    r"src\self_learning.py",
    r"src\skills.py",
    r"src\tower_economy.py",
    r"src\cogs\economy.py",
    r"src\agents\kimi_agent.py",
    r"src\mission_builder\dungeon_delve\room_generator.py",
    r"src\mission_builder\image_integration.py",
]

for rel_path in FILES_TO_FIX:
    fpath = os.path.join(ROOT, rel_path)
    if not os.path.exists(fpath):
        print(f"SKIP (not found): {rel_path}")
        continue
    
    with open(fpath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    for old, new in REPLACEMENTS:
        content = content.replace(old, new)
    
    if content != original:
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"FIXED: {rel_path}")
    else:
        print(f"NO CHANGE: {rel_path}")

print("\nDone!")