"""Fix \"\"\" (two straight double-quotes used as em-dash) across DB tables."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()
from src.db_api import raw_query, raw_execute

EM = "—"  # — em dash
OLD = '""'     # two straight double-quotes used as separator

fixes = [
    ("missions",        "title",            f"title LIKE '%{OLD}%'"),
    ("missions",        "faction",          f"faction LIKE '%{OLD}%'"),
    ("mission_outcomes","mission_title",     f"mission_title LIKE '%{OLD}%'"),
    ("mission_outcomes","notable_moments",   f"notable_moments LIKE '%{OLD}%'"),
    ("news_entries",    "headline",          f"headline LIKE '%{OLD}%'"),
    ("news_entries",    "body",              f"body LIKE '%{OLD}%'"),
]

for table, col, where in fixes:
    try:
        before = raw_query(f"SELECT COUNT(*) as n FROM {table} WHERE {where}")[0]["n"]
        if before:
            raw_execute(
                f"UPDATE {table} SET {col} = REPLACE({col}, %s, %s) WHERE {where}",
                (OLD, EM),
            )
            after = raw_query(f"SELECT COUNT(*) as n FROM {table} WHERE {where}")[0]["n"]
            print(f"  {table}.{col}: {before} rows fixed -> {after} remaining")
        else:
            print(f"  {table}.{col}: nothing to fix")
    except Exception as e:
        print(f"  {table}.{col}: ERROR {e}")

# mission_json is a JSON column — need to do it as text
try:
    before = raw_query(f"SELECT COUNT(*) as n FROM missions WHERE CAST(mission_json AS CHAR) LIKE '%{OLD}%'")[0]["n"]
    if before:
        raw_execute(
            "UPDATE missions SET mission_json = REPLACE(CAST(mission_json AS CHAR), %s, %s) "
            "WHERE CAST(mission_json AS CHAR) LIKE %s",
            (OLD, EM, f"%{OLD}%"),
        )
        after = raw_query(f"SELECT COUNT(*) as n FROM missions WHERE CAST(mission_json AS CHAR) LIKE '%{OLD}%'")[0]["n"]
        print(f"  missions.mission_json: {before} rows fixed -> {after} remaining")
    else:
        print(f"  missions.mission_json: nothing to fix")
except Exception as e:
    print(f"  missions.mission_json: ERROR {e}")

print("\nDone.")
