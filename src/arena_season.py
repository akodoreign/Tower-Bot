"""
arena_season.py — Argent Blades Arena Season Tracker

Tracks an ongoing arena season with:
- 12 active fighters (named, ranked, with win/loss records)
- Match results posted every 2-3 days
- Upsets, grudge matches, title bouts
- Season resets after a configurable number of matches
- Ties into NPC roster — roster NPCs can appear as fighters or be referenced

Persists to campaign_docs/arena_season.json
Posts to news channel as formatted results.
"""

from __future__ import annotations
import json, os, random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.log import logger

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
ARENA_FILE = DOCS_DIR / "arena_season.json"
TOWER_YEAR_OFFSET = 10

MATCHES_PER_SEASON = 30   # season resets after this many matches
MATCH_INTERVAL_MIN = 2 * 24 * 3600   # 2 days
MATCH_INTERVAL_MAX = 3 * 24 * 3600   # 3 days


def _dual_ts() -> str:
    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    return f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"


# ---------------------------------------------------------------------------
# Seed fighter roster — Argent Blades ranked season
# ---------------------------------------------------------------------------

_SEED_FIGHTERS = [
    {"name": "Aric Veyne",          "rank": 1,  "wins": 22, "losses": 3,  "title": "The Silver Spire",      "faction": "Argent Blades", "notes": "SS-Rank. Has not lost in fourteen months."},
    {"name": "Kassia Mor",          "rank": 2,  "wins": 18, "losses": 5,  "title": "The Ironwife",           "faction": "Argent Blades", "notes": "Known for ending fights early. Rarely takes damage."},
    {"name": "Brother Vex",         "rank": 3,  "wins": 15, "losses": 7,  "title": None,                    "faction": "Independent",   "notes": "Cult-trained. Movements that should not be physically possible."},
    {"name": "Drell the Unfinished","rank": 4,  "wins": 14, "losses": 8,  "title": "Crowd Favourite",        "faction": "Independent",   "notes": "Lost his right hand three seasons ago. Still ranked."},
    {"name": "Sela Vance",          "rank": 5,  "wins": 12, "losses": 9,  "title": None,                    "faction": "Wardens of Ash","notes": "Active Warden. Fights for extra income. Korin disapproves."},
    {"name": "The Composite",       "rank": 6,  "wins": 11, "losses": 10, "title": "Most Complaints Filed",  "faction": "Iron Fang",     "notes": "Suspected of illegal augmentation. FTA has an open file."},
    {"name": "Nara Fen",            "rank": 7,  "wins": 10, "losses": 10, "title": None,                    "faction": "Independent",   "notes": "Mari Fen's cousin. Does not acknowledge the connection."},
    {"name": "Priest of Ash",       "rank": 8,  "wins": 9,  "losses": 11, "title": None,                    "faction": "Serpent Choir", "notes": "Fights under divine contract terms. Wins count as Kharma donations."},
    {"name": "Mads Cutter",         "rank": 9,  "wins": 8,  "losses": 12, "title": None,                    "faction": "Independent",   "notes": "Veteran. Slow now. Still dangerous because he knows everything."},
    {"name": "The Patchwork Kid",   "rank": 10, "wins": 6,  "losses": 13, "title": "Most Injuries Per Bout", "faction": "Patchwork Saints","notes": "Pol Greaves trained them. Fights like someone who expects to lose."},
    {"name": "Lissa No-Name",       "rank": 11, "wins": 5,  "losses": 14, "title": None,                    "faction": "Independent",   "notes": "Nobody knows where she came from. Glass Sigil is interested."},
    {"name": "Gorvin Slate",        "rank": 12, "wins": 3,  "losses": 16, "title": "Crowd's Favourite Loser","faction": "Independent",   "notes": "Loses dramatically. Enormous fan base. Suspects the fix is in."},
]

_MATCH_TYPES = [
    "standard",     # routine ranked bout
    "standard",
    "standard",
    "grudge",       # personal beef, higher stakes
    "exhibition",   # non-ranked, crowd pleaser
    "title",        # only fires near top of standings
    "upset",        # explicit underdog win
]

_ARENAS = [
    "the main Arena of Ascendance pit",
    "the Arena's underground Cage circuit",
    "the open-air Dust Ring at Guild Spires East",
    "the Night Pits invitation bout",
    "the Grand Forum exhibition stage",
]


def _load_arena() -> Dict:
    if not ARENA_FILE.exists():
        return {}
    try:
        return json.loads(ARENA_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_arena(state: Dict) -> None:
    try:
        ARENA_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"Arena save error: {e}")


def _init_arena() -> Dict:
    now = datetime.now()
    return {
        "season":       1,
        "match_count":  0,
        "fighters":     _SEED_FIGHTERS,
        "last_match_at": None,
        "next_match_at": (now + timedelta(seconds=random.randint(MATCH_INTERVAL_MIN, MATCH_INTERVAL_MAX))).isoformat(),
        "last_posted_at": None,
        "match_log":    [],
    }


def _sort_fighters(fighters: List[Dict]) -> List[Dict]:
    """Sort by wins desc, losses asc."""
    return sorted(fighters, key=lambda f: (-f["wins"], f["losses"]))


def _run_match(state: Dict) -> Dict:
    """Simulate one match, update records, return match result dict."""
    fighters = state["fighters"]
    match_type = random.choice(_MATCH_TYPES)

    if match_type == "title" and fighters[0]["wins"] < 5:
        match_type = "standard"

    if match_type == "upset":
        # Pick underdog (rank 6-12) vs someone ranked higher
        underdogs = [f for f in fighters if f["rank"] >= 6]
        top_half  = [f for f in fighters if f["rank"] <= 5]
        if not underdogs or not top_half:
            match_type = "standard"
        else:
            fighter_b = random.choice(underdogs)
            fighter_a = random.choice(top_half)
            winner, loser = fighter_b, fighter_a  # underdog wins

    if match_type != "upset":
        if match_type == "title":
            fighter_a = fighters[0]
            fighter_b = fighters[1]
        elif match_type == "grudge":
            # Pick two fighters close in rank
            idx = random.randint(0, len(fighters) - 2)
            fighter_a = fighters[idx]
            fighter_b = fighters[idx + 1]
        else:
            f1, f2 = random.sample(fighters, 2)
            fighter_a, fighter_b = f1, f2

        # Higher rank has 60% win chance
        a_chance = 0.6 if fighter_a["rank"] < fighter_b["rank"] else 0.4
        winner = fighter_a if random.random() < a_chance else fighter_b
        loser  = fighter_b if winner == fighter_a else fighter_a

    # Apply outcome
    for f in state["fighters"]:
        if f["name"] == winner["name"]:
            f["wins"] += 1
        elif f["name"] == loser["name"]:
            f["losses"] += 1

    # Re-rank
    sorted_f = _sort_fighters(state["fighters"])
    for i, f in enumerate(sorted_f, 1):
        f["rank"] = i
    state["fighters"] = sorted_f

    arena_loc = random.choice(_ARENAS)
    result = {
        "match":      state["match_count"] + 1,
        "type":       match_type,
        "winner":     winner["name"],
        "loser":      loser["name"],
        "location":   arena_loc,
        "at":         datetime.now().isoformat(),
    }

    state["match_count"] += 1
    state["last_match_at"] = datetime.now().isoformat()
    state["next_match_at"] = (
        datetime.now() + timedelta(seconds=random.randint(MATCH_INTERVAL_MIN, MATCH_INTERVAL_MAX))
    ).isoformat()
    state["match_log"].append(result)
    state["match_log"] = state["match_log"][-50:]  # keep last 50 only

    # Season reset
    if state["match_count"] >= MATCHES_PER_SEASON:
        champion = state["fighters"][0]["name"]
        result["season_end"]   = True
        result["champion"]     = champion
        state["season"]       += 1
        state["match_count"]   = 0
        # Reset records but keep fighters
        for f in state["fighters"]:
            f["wins"], f["losses"] = 0, 0

    return result


def format_match_bulletin(result: Dict, state: Dict) -> str:
    match_type = result.get("type", "standard")
    winner     = result["winner"]
    loser      = result["loser"]
    location   = result.get("location", "the Arena")
    season     = state.get("season", 1)
    match_num  = result.get("match", "?")

    type_labels = {
        "standard":   "⚔️ RANKED BOUT",
        "grudge":     "🩸 GRUDGE MATCH",
        "exhibition": "🎭 EXHIBITION MATCH",
        "title":      "🏆 TITLE BOUT",
        "upset":      "💥 MAJOR UPSET",
    }
    header = type_labels.get(match_type, "⚔️ BOUT")

    # Find winner/loser records from state
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

    if w_data.get("notes"):
        lines.append(f"-# {winner}: {w_data['notes']}")

    if match_type == "upset":
        lines.append(f"\n📢 *The crowd did not expect that. Neither did {loser}.*")
    elif match_type == "title":
        lines.append(f"\n👑 *{winner} retains the top position. The title is not in dispute — yet.*")
    elif match_type == "grudge":
        lines.append(f"\n🩸 *Personal. The bad blood between these two runs deeper than rankings.*")

    if result.get("season_end"):
        champion = result.get("champion", winner)
        lines += [
            "",
            f"🏆 **SEASON {season - 1} COMPLETE**",
            f"*{champion} is crowned Season Champion. The board resets. Standings open.*",
        ]

    # Show top 5 standings
    top5 = state["fighters"][:5]
    lines += ["", "**CURRENT STANDINGS (Top 5):**"]
    for f in top5:
        title_str = f"  *{f['title']}*" if f.get("title") else ""
        lines.append(f"  #{f['rank']} {f['name']}  {f['wins']}W/{f['losses']}L{title_str}")

    lines += ["", "-# Argent Blades Arena of Ascendance. All bouts sanctioned. Betting through Iron Fang kiosks only."]
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
    """
    Called each bulletin cycle. If a match is due, run it and return a formatted bulletin.
    Returns None if no match is due yet.
    """
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
    """Full standings board — called on demand or weekly."""
    state = _load_arena()
    if not state:
        state = _init_arena()
        _save_arena(state)

    season   = state.get("season", 1)
    fighters = state.get("fighters", [])

    lines = [
        "🏟️ **ARENA OF ASCENDANCE — FULL STANDINGS** 🏟️",
        f"-# {_dual_ts()} │ Season {season}",
        "",
    ]
    for f in fighters:
        title_str   = f"  *{f['title']}*" if f.get("title") else ""
        faction_str = f"  [{f.get('faction','?')}]"
        lines.append(
            f"#{f['rank']}  **{f['name']}**  {f['wins']}W/{f['losses']}L{title_str}{faction_str}"
        )
    lines += ["", "-# Season standings updated after each sanctioned bout."]
    return "\n".join(lines)
