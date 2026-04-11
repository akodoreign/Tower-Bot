"""
arena_season.py — Argent Blades Arena Season Tracker
*** REFACTORED TO USE MySQL via db_api ***

Tracks an ongoing arena season with fighters, rankings, and match results.
"""

from __future__ import annotations
import json
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.log import logger
from src.db_api import raw_query, raw_execute, db

TOWER_YEAR_OFFSET = 10
MATCHES_PER_SEASON = 30
MATCH_INTERVAL_MIN = 2 * 24 * 3600
MATCH_INTERVAL_MAX = 3 * 24 * 3600


def _dual_ts() -> str:
    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    return f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"


_SEED_FIGHTERS = [
    {"name": "Aric Veyne",          "rank": 1,  "wins": 22, "losses": 3,  "title": "The Silver Spire",      "faction": "Argent Blades", "notes": "SS-Rank. Has not lost in fourteen months."},
    {"name": "Kassia Mor",          "rank": 2,  "wins": 18, "losses": 5,  "title": "The Ironwife",           "faction": "Argent Blades", "notes": "Known for ending fights early."},
    {"name": "Brother Vex",         "rank": 3,  "wins": 15, "losses": 7,  "title": None,                    "faction": "Independent",   "notes": "Cult-trained."},
    {"name": "Drell the Unfinished","rank": 4,  "wins": 14, "losses": 8,  "title": "Crowd Favourite",        "faction": "Independent",   "notes": "Lost his right hand three seasons ago."},
    {"name": "Sela Vance",          "rank": 5,  "wins": 12, "losses": 9,  "title": None,                    "faction": "Wardens of Ash","notes": "Active Warden. Fights for extra income."},
    {"name": "The Composite",       "rank": 6,  "wins": 11, "losses": 10, "title": "Most Complaints Filed",  "faction": "Iron Fang",     "notes": "Suspected of illegal augmentation."},
    {"name": "Nara Fen",            "rank": 7,  "wins": 10, "losses": 10, "title": None,                    "faction": "Independent",   "notes": "Mari Fen's cousin."},
    {"name": "Priest of Ash",       "rank": 8,  "wins": 9,  "losses": 11, "title": None,                    "faction": "Serpent Choir", "notes": "Fights under divine contract terms."},
    {"name": "Mads Cutter",         "rank": 9,  "wins": 8,  "losses": 12, "title": None,                    "faction": "Independent",   "notes": "Veteran. Slow now. Still dangerous."},
    {"name": "The Patchwork Kid",   "rank": 10, "wins": 6,  "losses": 13, "title": "Most Injuries Per Bout", "faction": "Patchwork Saints","notes": "Fights like someone who expects to lose."},
    {"name": "Lissa No-Name",       "rank": 11, "wins": 5,  "losses": 14, "title": None,                    "faction": "Independent",   "notes": "Nobody knows where she came from."},
    {"name": "Gorvin Slate",        "rank": 12, "wins": 3,  "losses": 16, "title": "Crowd's Favourite Loser","faction": "Independent",   "notes": "Loses dramatically. Enormous fan base."},
]

_MATCH_TYPES = ["standard", "standard", "standard", "grudge", "exhibition", "title", "upset"]
_ARENAS = [
    "the main Arena of Ascendance pit",
    "the Arena's underground Cage circuit",
    "the open-air Dust Ring at Guild Spires East",
    "the Night Pits invitation bout",
    "the Grand Forum exhibition stage",
]


def _load_arena() -> Dict:
    """Load arena state from database."""
    try:
        result = raw_query("SELECT * FROM arena_seasons ORDER BY id DESC LIMIT 1")
        if not result:
            return {}
        row = result[0]
        # champions_json contains the full state (we use it as our state storage)
        if row.get("champions_json"):
            state = row["champions_json"]
            if isinstance(state, str):
                state = json.loads(state)
            state["db_id"] = row["id"]
            return state
        return {}
    except Exception as e:
        logger.error(f"Arena load error: {e}")
        return {}


def _save_arena(state: Dict) -> None:
    """Save arena state to database."""
    try:
        db_id = state.pop("db_id", None)
        # Store full state in champions_json, standings in standings_json
        champions_json = json.dumps(state, ensure_ascii=False, default=str)
        standings_json = json.dumps(state.get("fighters", []), ensure_ascii=False, default=str)
        
        if db_id:
            raw_execute(
                "UPDATE arena_seasons SET season_number = %s, champions_json = %s, standings_json = %s WHERE id = %s",
                (state.get("season", 1), champions_json, standings_json, db_id)
            )
            state["db_id"] = db_id
        else:
            new_id = db.insert("arena_seasons", {
                "season_number": state.get("season", 1),
                "champions_json": champions_json,
                "standings_json": standings_json,
                "started_at": datetime.now(),
            })
            state["db_id"] = new_id
    except Exception as e:
        logger.error(f"Arena save error: {e}")


def _init_arena() -> Dict:
    now = datetime.now()
    return {
        "season":       1,
        "match_count":  0,
        "fighters":     _SEED_FIGHTERS.copy(),
        "last_match_at": None,
        "next_match_at": (now + timedelta(seconds=random.randint(MATCH_INTERVAL_MIN, MATCH_INTERVAL_MAX))).isoformat(),
        "match_log":    [],
    }


def _sort_fighters(fighters: List[Dict]) -> List[Dict]:
    return sorted(fighters, key=lambda f: (-f["wins"], f["losses"]))


def _run_match(state: Dict) -> Dict:
    """Simulate one match, update records, return match result dict."""
    fighters = state["fighters"]
    match_type = random.choice(_MATCH_TYPES)

    if match_type == "title" and fighters[0]["wins"] < 5:
        match_type = "standard"

    if match_type == "upset":
        underdogs = [f for f in fighters if f["rank"] >= 6]
        top_half  = [f for f in fighters if f["rank"] <= 5]
        if not underdogs or not top_half:
            match_type = "standard"
        else:
            fighter_b = random.choice(underdogs)
            fighter_a = random.choice(top_half)
            winner, loser = fighter_b, fighter_a

    if match_type != "upset":
        if match_type == "title":
            fighter_a, fighter_b = fighters[0], fighters[1]
        elif match_type == "grudge":
            idx = random.randint(0, len(fighters) - 2)
            fighter_a, fighter_b = fighters[idx], fighters[idx + 1]
        else:
            fighter_a, fighter_b = random.sample(fighters, 2)

        a_chance = 0.6 if fighter_a["rank"] < fighter_b["rank"] else 0.4
        winner = fighter_a if random.random() < a_chance else fighter_b
        loser  = fighter_b if winner == fighter_a else fighter_a

    for f in state["fighters"]:
        if f["name"] == winner["name"]:
            f["wins"] += 1
        elif f["name"] == loser["name"]:
            f["losses"] += 1

    sorted_f = _sort_fighters(state["fighters"])
    for i, f in enumerate(sorted_f, 1):
        f["rank"] = i
    state["fighters"] = sorted_f

    result = {
        "match":    state["match_count"] + 1,
        "type":     match_type,
        "winner":   winner["name"],
        "loser":    loser["name"],
        "location": random.choice(_ARENAS),
        "at":       datetime.now().isoformat(),
    }

    state["match_count"] += 1
    state["last_match_at"] = datetime.now().isoformat()
    state["next_match_at"] = (
        datetime.now() + timedelta(seconds=random.randint(MATCH_INTERVAL_MIN, MATCH_INTERVAL_MAX))
    ).isoformat()
    state["match_log"].append(result)
    state["match_log"] = state["match_log"][-50:]

    if state["match_count"] >= MATCHES_PER_SEASON:
        result["season_end"] = True
        result["champion"]   = state["fighters"][0]["name"]
        state["season"]     += 1
        state["match_count"] = 0
        for f in state["fighters"]:
            f["wins"], f["losses"] = 0, 0

    return result


def format_match_bulletin(result: Dict, state: Dict) -> str:
    match_type = result.get("type", "standard")
    winner, loser = result["winner"], result["loser"]
    location = result.get("location", "the Arena")
    season, match_num = state.get("season", 1), result.get("match", "?")

    type_labels = {"standard": "⚔️ RANKED BOUT", "grudge": "🩸 GRUDGE MATCH",
                   "exhibition": "🎭 EXHIBITION MATCH", "title": "🏆 TITLE BOUT", "upset": "💥 MAJOR UPSET"}
    header = type_labels.get(match_type, "⚔️ BOUT")

    w_data = next((f for f in state["fighters"] if f["name"] == winner), {})
    l_data = next((f for f in state["fighters"] if f["name"] == loser), {})

    lines = [
        f"🏟️ **ARENA OF ASCENDANCE — {header}** 🏟️",
        f"-# {_dual_ts()} │ Season {season}, Match {match_num}",
        "",
        f"**WINNER:** {winner}  ·  #{w_data.get('rank','?')}  ·  {w_data.get('wins',0)}W/{w_data.get('losses',0)}L",
        f"**DEFEATED:** {loser}  ·  #{l_data.get('rank','?')}  ·  {l_data.get('losses',0)}L",
        f"*Venue: {location}*",
    ]

    if result.get("season_end"):
        lines += ["", f"🏆 **SEASON {season - 1} COMPLETE** — *{result.get('champion')} crowned Champion.*"]

    top5 = state["fighters"][:5]
    lines += ["", "**CURRENT STANDINGS (Top 5):**"]
    for f in top5:
        title_str = f"  *{f['title']}*" if f.get("title") else ""
        lines.append(f"  #{f['rank']} {f['name']}  {f['wins']}W/{f['losses']}L{title_str}")

    return "\n".join(lines)


def should_post_arena() -> bool:
    state = _load_arena()
    if not state:
        return True
    next_at = state.get("next_match_at")
    if not next_at:
        return True
    try:
        return datetime.now() >= datetime.fromisoformat(next_at)
    except Exception:
        return True


async def tick_arena() -> Optional[str]:
    state = _load_arena()
    if not state:
        state = _init_arena()
    if not should_post_arena():
        _save_arena(state)
        return None
    result = _run_match(state)
    _save_arena(state)
    return format_match_bulletin(result, state)


def format_standings_bulletin() -> str:
    state = _load_arena()
    if not state:
        state = _init_arena()
        _save_arena(state)
    season, fighters = state.get("season", 1), state.get("fighters", [])
    lines = [f"🏟️ **ARENA OF ASCENDANCE — FULL STANDINGS** 🏟️", f"-# {_dual_ts()} │ Season {season}", ""]
    for f in fighters:
        title_str = f"  *{f['title']}*" if f.get("title") else ""
        lines.append(f"#{f['rank']}  **{f['name']}**  {f['wins']}W/{f['losses']}L{title_str}")
    return "\n".join(lines)
