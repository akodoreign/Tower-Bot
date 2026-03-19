"""
npc_lifecycle.py — Living NPC ecosystem for Tower of Last Chance.

NPCs are born, promoted, betrayed, revealed, and killed based on world events.
One new NPC injected per day minimum. Existing NPCs evolve via daily lifecycle events.
All changes persist in campaign_docs/npc_roster.json and campaign_docs/npc_roster.txt
(the .txt is what the RAG system reads).
"""

from __future__ import annotations

import os
import re
import json
import random
import asyncio
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.log import logger

DOCS_DIR          = Path(__file__).resolve().parent.parent / "campaign_docs"
NPC_JSON_FILE     = DOCS_DIR / "npc_roster.json"
NPC_TXT_FILE      = DOCS_DIR / "npc_roster.txt"
GRAVEYARD_FILE    = DOCS_DIR / "npc_graveyard.json"

# ---------------------------------------------------------------------------
# Factions and ranks
# ---------------------------------------------------------------------------

FACTIONS = [
    "Iron Fang Consortium",
    "Argent Blades",
    "Wardens of Ash",
    "Serpent Choir",
    "Obsidian Lotus",
    "Glass Sigil",
    "Patchwork Saints",
    "Adventurers Guild",
    "Guild of Ashen Scrolls",
    "Tower Authority",
    "Independent",
    "Brother Thane's Cult",
    "Wizards Tower",
]

FACTION_RANKS = {
    "Iron Fang Consortium":   ["Street Runner", "Acquisition Agent", "Senior Agent", "Floor Boss", "Underboss", "Guildmaster"],
    "Argent Blades":          ["Prospect", "Blade", "Senior Blade", "Champion", "Vanguard", "Guildmaster"],
    "Wardens of Ash":         ["Recruit", "Warden", "Sergeant", "Lieutenant", "Captain", "Commander"],
    "Serpent Choir":          ["Petitioner", "Acolyte", "Contract Scribe", "Mediator", "High Scribe", "High Apostle"],
    "Obsidian Lotus":         ["Ghost", "Operative", "Specialist", "Handler", "Shadow Director", "The Widow"],
    "Glass Sigil":            ["Junior Archivist", "Archivist", "Senior Archivist", "Sigil Master"],
    "Patchwork Saints":       ["Volunteer", "Saint", "Field Lead", "Field Captain", "Coordinator"],
    "Adventurers Guild":      ["Unranked", "F-Rank", "E-Rank", "D-Rank", "C-Rank", "B-Rank", "A-Rank", "S-Rank", "SS-Rank"],
    "Guild of Ashen Scrolls": ["Initiate", "Scribe", "Archivist Second Class", "Archivist First Class", "Senior Archivist", "Head Archivist"],
    "Tower Authority":        ["Compliance Intern", "Field Compliance Officer", "Senior Officer", "Magister", "Director"],
    "Independent":            ["Street Level", "Known Operator", "Respected Freelance", "City Legend"],
    "Brother Thane's Cult":   ["Follower", "Devoted", "Speaker", "Inner Circle", "Second", "Thane"],
    "Wizards Tower":           ["Apprentice", "Journeyman", "Researcher", "Senior Researcher", "Magister", "Archmage"],
}

SPECIES_LIST = [
    "Human", "Half-Elf", "Dwarf", "Tiefling", "Halfling", "Gnome",
    "Orc", "Half-Orc", "Dragonborn", "Elf", "Tabaxi", "Warforged",
    "Goblin", "Kobold", "Aasimar", "Genasi",
]

NPC_EVENTS = [
    "promotion",
    "demotion",
    "faction_defection",
    "revelation",
    "death",
    "resurrection",
    "alliance",
    "betrayal",
    "new_secret",
    "public_incident",
    "daily_generated",      # uses a fresh AI-generated event scenario
]

EVENT_WEIGHTS = [0.15, 0.08, 0.10, 0.15, 0.08, 0.02, 0.12, 0.10, 0.12, 0.08, 0.10]

# ---------------------------------------------------------------------------
# Daily generated event system
# ---------------------------------------------------------------------------

DAILY_EVENTS_FILE = DOCS_DIR / "daily_lifecycle_events.json"


def _load_daily_events() -> dict:
    if not DAILY_EVENTS_FILE.exists():
        return {}
    try:
        return json.loads(DAILY_EVENTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_daily_events(data: dict) -> None:
    try:
        DAILY_EVENTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _needs_new_daily_events() -> bool:
    data = _load_daily_events()
    return data.get("date") != datetime.now().strftime("%Y-%m-%d")


async def refresh_daily_events_if_needed() -> None:
    """Generate 5 fresh, specific lifecycle event scenarios for today.
    Called at lifecycle startup. No-op if already generated today."""
    if not _needs_new_daily_events():
        return

    from src.ollama_busy import is_available
    if not is_available():
        return

    prompt = f"""{_LORE}

You are generating SPECIFIC lifecycle event scenarios for NPCs in the Undercity.
These are one-time events that happen to individual NPCs today.

Generate exactly 5 unique event scenarios. Each should be:
- A specific, dramatic situation (not generic like "gets promoted")
- Grounded in the Undercity setting — factions, districts, economy, Rifts
- Something that changes an NPC's status, relationships, or reputation
- 1-2 sentences describing WHAT HAPPENS (the lifecycle system will pick an NPC to apply it to)

Examples of good events:
- "Caught smuggling Rift residue samples to an outside buyer. Faction is deciding whether to cover it up or make an example."
- "Saved three children from a collapsing Warrens building. Suddenly famous in a district where fame is dangerous."
- "Received a sealed letter from a dead faction member — contents unknown, but they've been acting strange since."
- "Publicly accused a senior faction member of skimming funds. Either very brave or very stupid."
- "Found unconscious near a sealed Rift zone with no memory of the last 48 hours."

RULES:
- Output exactly 5 lines, one event per line.
- No numbering, no bullets, no preamble.
- Each event should be usable for ANY NPC regardless of faction.
- Vary the tone: some dangerous, some political, some personal, some supernatural.
- If your output contains anything other than 5 lines, you have failed."""

    text = await _generate(prompt)
    if not text:
        logger.warning("🧬 Daily event generation failed")
        return

    events = [l.strip() for l in text.splitlines() if l.strip()][:5]
    if not events:
        return

    today = datetime.now().strftime("%Y-%m-%d")
    _save_daily_events({"date": today, "events": events})
    logger.info(f"🧬 Generated {len(events)} daily lifecycle events for {today}")


def _get_random_daily_event() -> Optional[str]:
    """Return one random event from today's generated list, or None."""
    data = _load_daily_events()
    events = data.get("events", [])
    return random.choice(events) if events else None


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_npcs() -> List[dict]:
    if not NPC_JSON_FILE.exists():
        return []
    try:
        return json.loads(NPC_JSON_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_npcs(npcs: List[dict]) -> None:
    try:
        NPC_JSON_FILE.write_text(json.dumps(npcs, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"NPC save error: {e}")
    _rebuild_txt(npcs)


def _rebuild_txt(npcs: List[dict]) -> None:
    """Rewrite npc_roster.txt from current JSON so RAG stays in sync.
    Dead NPCs are excluded — they live in npc_graveyard.json instead."""
    lines = [
        "# NPC ROSTER — TOWER OF LAST CHANCE",
        "# Auto-generated from npc_lifecycle system. Do not edit manually.",
        f"# Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"# Active NPCs: {len([n for n in npcs if n.get('status') != 'dead'])}",
        "",
    ]
    for npc in npcs:
        # Skip dead NPCs — they should be in the graveyard, not the active RAG context
        if npc.get("status") == "dead":
            continue
        lines.append("---NPC---")
        lines.append(f"NAME: {npc.get('name', 'Unknown')}")
        lines.append(f"STATUS: {npc.get('status', 'alive')}")
        lines.append(f"FACTION: {npc.get('faction', 'Independent')}")
        lines.append(f"RANK: {npc.get('rank', 'Unknown')}")
        lines.append(f"SPECIES: {npc.get('species', 'Human')}")
        lines.append(f"AGE: {npc.get('age', 'Unknown')}")
        if npc.get("appearance"):
            lines.append(f"APPEARANCE: {npc['appearance']}")
        if npc.get("location"):
            lines.append(f"LOCATION: {npc['location']}")
        lines.append(f"MOTIVATION: {npc.get('motivation', '')}")
        lines.append(f"ROLE: {npc.get('role', '')}")
        if npc.get("secret"):
            lines.append(f"SECRET: {npc['secret']}")
        if npc.get("revealed_secrets"):
            lines.append(f"REVEALED: {' | '.join(npc['revealed_secrets'])}")
        if npc.get("relationships"):
            lines.append(f"RELATIONSHIPS: {npc['relationships']}")
        if npc.get("oracle_notes"):
            lines.append(f"ORACLE NOTES: {npc['oracle_notes']}")
        if npc.get("history"):
            lines.append(f"HISTORY: {' | '.join(npc['history'][-5:])}")
        lines.append("---END NPC---")
        lines.append("")
    try:
        NPC_TXT_FILE.write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:
        logger.error(f"NPC txt rebuild error: {e}")


# ---------------------------------------------------------------------------
# Graveyard — dead NPCs are moved here with full data preserved
# ---------------------------------------------------------------------------

def _load_graveyard() -> List[dict]:
    if not GRAVEYARD_FILE.exists():
        return []
    try:
        return json.loads(GRAVEYARD_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_graveyard(graveyard: List[dict]) -> None:
    try:
        GRAVEYARD_FILE.write_text(json.dumps(graveyard, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.error(f"Graveyard save error: {e}")


def _move_to_graveyard(npc: dict, npcs: List[dict]) -> None:
    """Move a dead NPC from the active roster to the graveyard.
    Preserves all data. Removes from the npcs list in-place."""
    graveyard = _load_graveyard()

    # Avoid duplicates in graveyard
    if any(g.get("name") == npc.get("name") and g.get("created_at") == npc.get("created_at")
           for g in graveyard):
        logger.debug(f"💀 {npc.get('name')} already in graveyard — skipping")
    else:
        npc["moved_to_graveyard_at"] = datetime.now().isoformat()
        graveyard.append(npc)
        _save_graveyard(graveyard)
        logger.info(f"💀 {npc.get('name')} moved to graveyard ({len(graveyard)} total in graveyard)")

    # Remove from active roster
    try:
        npcs.remove(npc)
    except ValueError:
        # Already removed or not in list
        pass


def _sweep_dead_to_graveyard(npcs: List[dict]) -> int:
    """Sweep any dead NPCs still in the active roster to the graveyard.
    Called on startup to clean up any that weren't moved at death time.
    Returns count of NPCs moved."""
    dead = [n for n in npcs if n.get("status") == "dead"]
    if not dead:
        return 0

    graveyard = _load_graveyard()
    moved = 0
    for npc in dead:
        # Avoid duplicates
        if any(g.get("name") == npc.get("name") and g.get("created_at") == npc.get("created_at")
               for g in graveyard):
            continue
        npc["moved_to_graveyard_at"] = datetime.now().isoformat()
        graveyard.append(npc)
        moved += 1

    if moved:
        _save_graveyard(graveyard)

    # Remove all dead from active roster
    for npc in dead:
        try:
            npcs.remove(npc)
        except ValueError:
            pass

    if dead:
        _save_npcs(npcs)
        logger.info(f"💀 Graveyard sweep: moved {moved} dead NPCs, removed {len(dead)} from active roster")

    return len(dead)


# ---------------------------------------------------------------------------
# Ollama generation helper
# ---------------------------------------------------------------------------

async def _generate(prompt: str) -> Optional[str]:
    import httpx
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()
        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()
        lines = text.splitlines()
        skip = ("sure", "here's", "here is", "as requested", "certainly",
                "of course", "i hope", "below is", "absolutely")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        return "\n".join(lines).strip() or None
    except Exception as e:
        logger.error(f"npc_lifecycle _generate error: {e}")
        return None


# ---------------------------------------------------------------------------
# World lore reference
# ---------------------------------------------------------------------------

_LORE = """\
SETTING: The Undercity — a sealed city under a Dome around the Tower of Last Chance.
Rifts tear reality constantly. Adventurers are an economic class. Gods harvest heroic souls.
FACTIONS (use ONLY these): Iron Fang Consortium, Argent Blades, Wardens of Ash, Serpent Choir,
Obsidian Lotus, Glass Sigil, Patchwork Saints, Adventurers Guild, Guild of Ashen Scrolls,
Tower Authority, Wizards Tower, Independent, Brother Thane's Cult.
TONE: Dark urban fantasy. Gritty, specific, noir. No generic fantasy filler.\
"""


# ---------------------------------------------------------------------------
# Generate a brand new NPC
# ---------------------------------------------------------------------------

async def generate_new_npc(existing_npcs: List[dict]) -> Optional[dict]:
    faction  = random.choice(FACTIONS)
    ranks    = FACTION_RANKS.get(faction, ["Member"])
    rank     = ranks[random.randint(0, min(2, len(ranks) - 1))]
    species  = random.choice(SPECIES_LIST)

    existing_names = [n.get("name", "") for n in existing_npcs]
    names_block    = ", ".join(existing_names[-20:]) if existing_names else "none yet"

    prompt = f"""{_LORE}

Existing NPC names (do NOT reuse these): {names_block}

Generate ONE new NPC for the Undercity. They should feel like a real person, not a plot device.
Rank-and-file level — not a faction leader, not a legendary hero.

Required faction: {faction}
Required rank: {rank}
Required species: {species}

Output ONLY a JSON object with these exact keys, nothing else:
{{
  "name": "Full name",
  "faction": "{faction}",
  "rank": "{rank}",
  "species": "{species}",
  "age": "number or range like 30s",
  "appearance": "2 sentences — specific physical details, how they carry themselves",
  "location": "specific district and sub-location",
  "motivation": "2 sentences — what they actually want and why",
  "role": "1 sentence — what they do day to day",
  "secret": "1-2 sentences — something hidden that could change everything if revealed",
  "relationships": "1-2 sentences — notable connections to other people or factions",
  "oracle_notes": "1-2 sentences — what the Oracle would sense about this person"
}}

RULES:
- Be specific. Invent a real name, real location, real secret.
- Secret should be genuinely interesting — hidden identity, crime, loyalty, supernatural fact.
- Do NOT output anything except the JSON object.
- Do NOT use markdown code fences."""

    text = await _generate(prompt)
    if not text:
        return None

    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

    try:
        data = json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            logger.warning(f"NPC generation: could not parse JSON:\n{text[:200]}")
            return None
        try:
            data = json.loads(match.group())
        except Exception:
            logger.warning("NPC generation: JSON extraction failed")
            return None

    return {
        "name":             data.get("name", "Unknown"),
        "faction":          data.get("faction", faction),
        "rank":             data.get("rank", rank),
        "species":          data.get("species", species),
        "age":              str(data.get("age", "unknown")),
        "appearance":       data.get("appearance", ""),
        "location":         data.get("location", ""),
        "motivation":       data.get("motivation", ""),
        "role":             data.get("role", ""),
        "secret":           data.get("secret", ""),
        "relationships":    data.get("relationships", ""),
        "oracle_notes":     data.get("oracle_notes", ""),
        "status":           "alive",
        "revealed_secrets": [],
        "history":          [f"[{datetime.now().strftime('%Y-%m-%d')}] Introduced to the Undercity roster."],
        "created_at":       datetime.now().isoformat(),
        "last_event_at":    datetime.now().isoformat(),
    }


# ---------------------------------------------------------------------------
# Apply a lifecycle event to an existing NPC
# ---------------------------------------------------------------------------

async def apply_npc_event(npc: dict, all_npcs: List[dict]) -> Optional[str]:
    # ── Injured NPCs: resolve before anything else ────────────────────────────
    # 90% recover, 10% die. Either way generate a bulletin explaining the outcome.
    if npc.get("status") == "injured":
        event = "injury_recovery" if random.random() < 0.90 else "injury_death"

    # ── Dead NPCs: only resurrection (5% chance), otherwise skip ─────────────
    elif npc.get("status") == "dead":
        if random.random() < 0.05:
            event = "resurrection"
        else:
            return None

    else:
        event = random.choices(NPC_EVENTS, weights=EVENT_WEIGHTS, k=1)[0]

        # Protect faction leaders from random death — they can only die via DM action
        if event == "death" and is_faction_leader(npc.get("name", "")):
            logger.info(f"\U0001f451 Protected leader {npc.get('name')} from random death — rerolling event")
            event = random.choice(["promotion", "public_incident", "new_secret", "revelation"])

    name    = npc.get("name", "Unknown")
    faction = npc.get("faction", "Independent")
    rank    = npc.get("rank", "Member")
    species = npc.get("species", "Human")
    today   = datetime.now().strftime("%Y-%m-%d")
    announcement = None

    if event == "promotion":
        ranks       = FACTION_RANKS.get(faction, ["Member"])
        current_idx = ranks.index(rank) if rank in ranks else 0
        if current_idx < len(ranks) - 1:
            new_rank    = ranks[current_idx + 1]
            npc["rank"] = new_rank
            npc["history"].append(f"[{today}] Promoted from {rank} to {new_rank} within {faction}.")
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {species}, {faction}.\n"
                f"Event: Promoted from {rank} to {new_rank}.\n"
                f"Write a 2-3 line in-character Undercity bulletin. Gritty, specific, real consequences implied.\n"
                f"No preamble. Output only the bulletin."
            )

    elif event == "demotion":
        ranks       = FACTION_RANKS.get(faction, ["Member"])
        current_idx = ranks.index(rank) if rank in ranks else 0
        if current_idx > 0:
            new_rank    = ranks[current_idx - 1]
            npc["rank"] = new_rank
            npc["history"].append(f"[{today}] Demoted from {rank} to {new_rank} within {faction}.")
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {faction}.\n"
                f"Event: Demoted from {rank} to {new_rank}. Imply something went wrong.\n"
                f"Write a 2-3 line Undercity bulletin. No preamble. Output only the bulletin."
            )

    elif event == "faction_defection":
        new_faction    = random.choice([f for f in FACTIONS if f != faction])
        new_rank       = FACTION_RANKS.get(new_faction, ["Member"])[0]
        old_faction    = faction
        npc["faction"] = new_faction
        npc["rank"]    = new_rank
        npc["history"].append(f"[{today}] Defected from {old_faction} to {new_faction} (rank: {new_rank}).")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}.\n"
            f"Event: Defected from {old_faction} to {new_faction}. Now ranked {new_rank}.\n"
            f"Write a 2-3 line Undercity bulletin. Imply motivation without explaining fully.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "revelation":
        secret = npc.get("secret", "")
        if secret and secret not in npc.get("revealed_secrets", []):
            npc.setdefault("revealed_secrets", []).append(secret)
            npc["secret"] = ""
            npc["history"].append(f"[{today}] Secret revealed: {secret[:60]}...")
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
                f"Their secret was: {secret}\n"
                f"Write a 2-3 line Undercity bulletin announcing the revelation as city gossip.\n"
                f"Do NOT just restate the secret. No preamble. Output only the bulletin."
            )

    elif event == "death":
        npc["status"] = "dead"
        npc["history"].append(f"[{today}] Killed. Faction: {faction}, Rank: {rank}.")
        _death_cause = random.choice([
            # Faction violence
            "assassinated by a faction rival — clean job, no witnesses",
            "killed in a turf war between two factions over a market lane",
            "executed by their own faction for a betrayal, real or suspected",
            "found in the canal with weights on their ankles — Iron Fang message",
            "taken out by an Obsidian Lotus contract, cause of payment unknown",
            "throat cut during a faction meeting gone wrong",
            "disappeared after crossing the wrong underboss — body found three days later",
            # Street / criminal violence
            "killed in a street brawl that got out of hand — wrong weapon drawn",
            "shot dead during an armed robbery of a market stall",
            "stabbed in a debt dispute that escalated beyond anyone's intention",
            "beaten to death by a crew who mistook them for someone else",
            "killed by a bounty hunter acting on a contract that wasn't even accurate",
            # Transport and industrial
            "run down by a cargo hauler at a Warrens crossroads, driver fled",
            "fell under a tube train at the outer platform during rush hour",
            "crushed in a Scrapworks crane accident — safety record already poor",
            "killed in a Scrapworks explosion caused by improperly stored fuel",
            "fell from the upper level of a Spires construction site",
            "buried in a Warrens structural collapse they were warned about",
            # Dungeon / mission
            "didn't come back from a dungeon contract — party returned without them",
            "killed inside a Rift incursion zone, remains partially recovered",
            "monster encounter on a dungeon run — outmatched and alone",
            "trap in an unexplored sublevel — no one saw it trigger",
            # Occupational / consequence
            "poisoned — slow enough that they didn't know until too late",
            "kneecapped and left in the cold, bled out before anyone found them",
            "died in custody after Warden arrest — official cause listed as natural",
            "overdose — deliberate or otherwise, city isn't sure",
            # Rift (rare, not default)
            "killed in a full Rift breach event in the Outer Wall district",
            "consumed by a Rift tear — no body, just a scorch mark",
        ])
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Cause of death: {_death_cause}.\n"
            f"Write a 2-3 line Undercity death notice. Terse. Real. Use the specific cause above.\n"
            f"Do NOT default to 'Rift exposure' or generic fantasy causes.\n"
            f"No preamble. Output only the notice."
        )

    # --- INJURY RECOVERY ---
    elif event == "injury_recovery":
        npc["status"] = "alive"
        npc["history"].append(f"[{today}] Recovered from injuries.")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Event: Was injured. Has now recovered and is back on their feet.\n"
            f"Write a 2-3 line Undercity bulletin. Terse, specific — what happened, how they got through it.\n"
            f"Imply the experience may have changed them. No preamble. Output only the bulletin."
        )

    # --- INJURY → DEATH ---
    elif event == "injury_death":
        npc["status"] = "dead"
        npc["history"].append(f"[{today}] Succumbed to injuries. Faction: {faction}, Rank: {rank}.")
        _complication = random.choice([
            "infection set in and Patchwork Saints couldn't hold it",
            "internal bleeding that wasn't caught in time",
            "lost too much blood before help arrived",
            "the wound was deeper than it looked — organ damage",
            "no credits for a proper healer, Saints clinic did what they could",
            "fever took hold on the third day, didn't break",
            "complications from surgery in an underfunded Warrens clinic",
            "second attack on them in the clinic finished the job",
            "they refused treatment until it was too late",
            "head injury that seemed minor turned out not to be",
        ])
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Event: Was injured and did not recover. Complication: {_complication}.\n"
            f"Write a 2-3 line Undercity death notice. Terse. Real.\n"
            f"Imply the complication — don't write 'Rift exposure' as the cause.\n"
            f"No preamble. Output only the notice."
        )

    elif event == "resurrection":
        npc["status"] = "alive"
        npc["history"].append(f"[{today}] Returned from death. Changed.")
        new_secret = await _generate(
            f"NPC {name} has returned from death in the Undercity.\n"
            f"Generate ONE new secret they now carry. Something changed. Something wrong.\n"
            f"Output ONLY the secret in 1-2 sentences. No preamble."
        )
        if new_secret:
            npc["secret"] = new_secret
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, previously of {faction}.\n"
            f"Event: Has returned from death. Unexplained. Changed.\n"
            f"Write a 2-3 line Undercity bulletin. Unsettling. Raise questions, answer none.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "alliance":
        candidates = [n for n in all_npcs if n.get("name") != name and n.get("status") == "alive"]
        if candidates:
            ally         = random.choice(candidates)
            ally_name    = ally.get("name", "Unknown")
            ally_faction = ally.get("faction", "Unknown")
            npc["history"].append(f"[{today}] Formed alliance with {ally_name} ({ally_faction}).")
            npc["relationships"] = npc.get("relationships", "") + f" | Alliance with {ally_name} ({ally_faction})."
            announcement = await _generate(
                f"{_LORE}\nNPC: {name} ({faction}) has formed a notable alliance with {ally_name} ({ally_faction}).\n"
                f"Write a 2-3 line Undercity bulletin. What does it mean for the balance of power?\n"
                f"No preamble. Output only the bulletin."
            )

    elif event == "betrayal":
        npc["history"].append(f"[{today}] Committed a significant betrayal within {faction}.")
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Event: Has betrayed someone within their faction. Details not fully known.\n"
            f"Write a 2-3 line Undercity rumour bulletin. Something happened. Nobody saying exactly what.\n"
            f"No preamble. Output only the bulletin."
        )

    elif event == "new_secret":
        new_secret = await _generate(
            f"NPC {name} is a {rank} in {faction} in a dark fantasy underground city.\n"
            f"Generate ONE new secret — hidden identity, unexpected loyalty, supernatural fact, crime.\n"
            f"Example: 'Is secretly a werecoyote who has not yet transformed in the Undercity.'\n"
            f"Output ONLY the secret in 1-2 sentences. No preamble."
        )
        if new_secret:
            npc["secret"] = new_secret
            npc["history"].append(f"[{today}] New secret acquired.")
        return None  # no public announcement

    elif event == "public_incident":
        announcement = await _generate(
            f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
            f"Event: Involved in a public incident — confrontation, accident, spectacle, or arrest.\n"
            f"Write a 2-3 line Undercity bulletin. Specific. Atmospheric.\n"
            f"No preamble. Output only the bulletin."
        )
        if announcement:
            npc["history"].append(f"[{today}] Public incident.")

    elif event == "daily_generated":
        scenario = _get_random_daily_event()
        if scenario:
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {species}, {faction}, {rank}.\n"
                f"Location: {npc.get('location', 'the Undercity')}.\n"
                f"Role: {npc.get('role', 'active in their faction')}.\n"
                f"TODAY'S EVENT: {scenario}\n\n"
                f"Write a 2-3 line Undercity bulletin about this event happening to {name}.\n"
                f"Ground it in their specific faction, rank, and role. Make it feel personal.\n"
                f"Tone: gritty, specific, consequential.\n"
                f"No preamble. Output only the bulletin."
            )
            if announcement:
                npc["history"].append(f"[{today}] {scenario[:80]}{'...' if len(scenario) > 80 else ''}")
                logger.info(f"🧬 Daily event for {name}: {scenario[:60]}")
        else:
            # No daily events available — fall back to public incident
            announcement = await _generate(
                f"{_LORE}\nNPC: {name}, {faction}, {rank}.\n"
                f"Event: Involved in a public incident.\n"
                f"Write a 2-3 line Undercity bulletin. No preamble. Output only the bulletin."
            )
            if announcement:
                npc["history"].append(f"[{today}] Public incident.")

    npc["last_event_at"] = datetime.now().isoformat()

    # If the NPC just died, move them to the graveyard
    if npc.get("status") == "dead":
        _move_to_graveyard(npc, all_npcs)

    return announcement


# ---------------------------------------------------------------------------
# Seed from static npc_roster.txt (first run only)
# ---------------------------------------------------------------------------

def _seed_from_txt() -> List[dict]:
    if not NPC_TXT_FILE.exists():
        return []
    header = NPC_TXT_FILE.read_text(encoding="utf-8", errors="ignore")[:200]
    if "Auto-generated" in header:
        return []
    npcs = []
    text = NPC_TXT_FILE.read_text(encoding="utf-8", errors="ignore")
    for block in re.split(r"---NPC---", text):
        block = block.strip()
        if not block or "---END NPC---" not in block:
            continue
        block = block.split("---END NPC---")[0].strip()
        npc = {}
        for line in block.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                npc[key.strip().lower().replace(" ", "_")] = value.strip()
        if "name" not in npc:
            continue
        npcs.append({
            "name":             npc.get("name", "Unknown"),
            "faction":          npc.get("faction", "Independent"),
            "rank":             npc.get("rank", "Member"),
            "species":          npc.get("species", "Human"),
            "age":              npc.get("age", "unknown"),
            "appearance":       npc.get("appearance", ""),
            "location":         npc.get("location", ""),
            "motivation":       npc.get("motivation", ""),
            "role":             npc.get("role", ""),
            "secret":           npc.get("secret", ""),
            "relationships":    npc.get("relationships", ""),
            "oracle_notes":     npc.get("oracle_notes", ""),
            "status":           "alive",
            "revealed_secrets": [],
            "history":          [f"[{datetime.now().strftime('%Y-%m-%d')}] Entered roster from static file."],
            "created_at":       datetime.now().isoformat(),
            "last_event_at":    datetime.now().isoformat(),
        })
    return npcs


# ---------------------------------------------------------------------------
# Main daily lifecycle tick
# ---------------------------------------------------------------------------

async def run_daily_lifecycle(channel) -> None:
    import discord

    # Skip if Ollama is busy with a long-running task (e.g. module generation)
    from src.ollama_busy import is_available, get_busy_reason
    if not is_available():
        logger.info(f"🧬 Ollama busy ({get_busy_reason()}) — skipping lifecycle cycle")
        return

    # Generate fresh daily event scenarios if stale
    try:
        await refresh_daily_events_if_needed()
    except Exception as e:
        logger.warning(f"🧬 Daily event refresh failed: {e}")

    # Seed on first run
    npcs = _load_npcs()

    # Sweep any dead NPCs still in the active roster to the graveyard.
    # On first run after this update, this catches the 5 existing dead NPCs.
    # After that, deaths are moved instantly by apply_npc_event.
    swept = _sweep_dead_to_graveyard(npcs)
    if swept:
        npcs = _load_npcs()  # reload — sweep modified and saved the list

    if not npcs:
        logger.info("🧬 Seeding NPC roster from static file...")
        npcs = _seed_from_txt()
        if npcs:
            _save_npcs(npcs)
            logger.info(f"🧬 Seeded {len(npcs)} NPCs from static roster.")

    # Generate 1 new NPC
    new_npc = await generate_new_npc(npcs)
    if new_npc:
        npcs.append(new_npc)
        _save_npcs(npcs)
        logger.info(f"🧬 New NPC: {new_npc['name']} ({new_npc['faction']}, {new_npc['rank']})")

        # Auto-generate appearance profile for the new NPC so they're immediately
        # usable in story image prompts and captions without a manual /gearrun.
        try:
            from src.npc_appearance import _generate_npc_profile, _profile_path
            import json as _json
            profile = await _generate_npc_profile(new_npc)
            _profile_path(new_npc["name"]).write_text(
                _json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            # Rebuild the flat lookup so find_npc_in_text() picks them up immediately
            from src.npc_appearance import get_all_sd_prompts, NPC_APP_DIR
            flat = get_all_sd_prompts()
            flat[new_npc["name"]] = profile.get("sd_appearance", "")
            (NPC_APP_DIR / "_all_sd_prompts.json").write_text(
                _json.dumps(flat, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            logger.info(f"🎨 Appearance profile generated for new NPC: {new_npc['name']}")
        except Exception as _ae:
            logger.warning(f"🎨 Appearance profile failed for {new_npc['name']}: {_ae}")

        intro = await _generate(
            f"{_LORE}\n"
            f"A new person has stepped into relevance in the Undercity.\n"
            f"Name: {new_npc['name']}\nFaction: {new_npc['faction']}\nRank: {new_npc['rank']}\n"
            f"Species: {new_npc['species']}\nRole: {new_npc['role']}\nLocation: {new_npc['location']}\n"
            f"Write a SHORT 2-3 line bulletin introducing them as someone the city is starting to notice.\n"
            f"Do NOT reveal their secret. No preamble. Output only the bulletin."
        )
        if intro and channel:
            embed = discord.Embed(
                title=f"👤 New Face — {new_npc['name']}",
                description=intro,
                color=discord.Color.teal()
            )
            embed.set_footer(text=f"{new_npc['rank']} · {new_npc['faction']} · {new_npc['species']}")
            await channel.send(embed=embed)

    # Roll events for 1-3 existing NPCs
    # Include injured NPCs — they MUST resolve on the next cycle
    alive_npcs       = [n for n in npcs if n.get("status") == "alive"]
    injured_npcs     = [n for n in npcs if n.get("status") == "injured"]
    # Injured NPCs are always included; sample from alive for the remainder
    sample_count     = max(0, random.randint(1, 3) - len(injured_npcs))
    sampled_alive    = random.sample(alive_npcs, min(sample_count, len(alive_npcs)))
    event_candidates = injured_npcs + sampled_alive

    for npc in event_candidates:
        # Injured NPCs ALWAYS resolve — skip the cooldown check for them.
        # Alive NPCs respect the 3-day cooldown so we don't spam the same person.
        if npc.get("status") != "injured":
            last_event = npc.get("last_event_at", "")
            if last_event:
                try:
                    if (datetime.now() - datetime.fromisoformat(last_event)).days < 3:
                        continue
                except Exception:
                    pass

        announcement = await apply_npc_event(npc, npcs)
        _save_npcs(npcs)

        if announcement and channel:
            is_dead = npc.get("status") == "dead"
            embed = discord.Embed(
                description=announcement,
                color=discord.Color.dark_red() if is_dead else discord.Color.blurple()
            )
            embed.set_footer(
                text=f"{'💀' if is_dead else '📰'} {npc['name']} · {npc.get('faction','?')} · {npc.get('rank','?')}"
            )
            await channel.send(embed=embed)

        await asyncio.sleep(5)

    # --- Daily Injury Wave: 1-2 NPCs get injured each cycle ---
    # Capped at MAX_CONCURRENT_INJURED so injuries don't pile up between reboots.
    # Separate from the main event loop — picks from alive NPCs not already processed this run.
    # Uses a 1-day cooldown (not 3) so fresh NPCs can be injured sooner.
    MAX_CONCURRENT_INJURED = 3
    currently_injured = len([n for n in npcs if n.get("status") == "injured"])
    injury_slots = max(0, MAX_CONCURRENT_INJURED - currently_injured)

    already_processed_ids = {id(n) for n in event_candidates}
    injury_pool = [
        n for n in alive_npcs
        if id(n) not in already_processed_ids
        and (
            not n.get("last_event_at")
            or (datetime.now() - datetime.fromisoformat(n["last_event_at"])).total_seconds() > 86400
        )
    ]
    random.shuffle(injury_pool)
    wave_count = min(random.randint(1, 2), injury_slots)
    injury_targets = injury_pool[:wave_count]
    today_str = datetime.now().strftime("%Y-%m-%d")

    for npc in injury_targets:
        npc["status"]        = "injured"
        npc["last_event_at"] = datetime.now().isoformat()
        npc["history"].append(f"[{today_str}] Injured.")
        _save_npcs(npcs)

        _injury_cause = random.choice([
            # Street violence
            "stabbed in a street fight over a debt or territory dispute",
            "jumped by a rival faction crew in an alley, beaten badly",
            "knifed outside a Night Pits bout — wrong person, wrong moment",
            "took a bolt from a crossbow during a Crimson Alley ambush",
            "glassed in a bar fight at the Adventurer's Inn",
            "caught in crossfire between two faction crews settling a score",
            "shot with an illegal firearm during a market dispute that escalated",
            "beaten by Warden enforcers during a raid, no charges filed",
            "shanked by a contract killer — survived, barely",
            "brawl at the Arena spilled into the street, took the worst of it",
            # Transport accidents (the Undercity has vehicles)
            "hit by a cargo hauler truck barreling through a market lane",
            "struck by a delivery van running a red on a Warrens intersection",
            "fell from a moving freight cart while trying to board it",
            "clipped by a fast-moving cargo bike and thrown into a concrete pillar",
            "hit by an underground tube train — stepped too close to the platform edge",
            "knocked off a loading platform by a reversing transport truck",
            "crushed between two freight containers during a docking accident",
            "fell off the back of a moving faction vehicle during a chase",
            "struck by a runaway electric cart that lost its brakes on a ramp",
            "dragged under a slow-moving ore hauler in the Scrapworks",
            # Industrial / environmental
            "industrial accident at the Scrapworks — crane cable snapped",
            "scalded by a burst steam pipe in the maintenance tunnels",
            "fell through a rusted grate in the Warrens into the level below",
            "buried under a partial ceiling collapse in the Outer Wall sector",
            "electrical burn from an illegal junction box they were tapping",
            "caught in a Scrapworks welding explosion",
            "fell from scaffolding in the mid-construction area of a Spires tower",
            "chemical burn from improperly stored reagents in a market stall",
            "trapped in a structural collapse in the older Sanctum Quarter tunnels",
            "crushed by a falling market stall during a crowd panic",
            # Dungeon incursion / mission gone wrong
            "returned from a dungeon run missing two fingers — won't say which level",
            "mauled by something in the lower corridors of a Rift incursion zone",
            "took a floor trap to the leg on a contracted delve",
            "burned by a dungeon guardian's breath weapon inside a Rift boundary",
            "fell into a spiked pit trap in an unexplored Undercity sublevel",
            "came back from a dungeon contract half-conscious, gear destroyed",
            "bitten by an unknown creature encountered in an unmapped tunnel",
            # Occupational hazards
            "assaulted during a collection run for the Iron Fang Consortium",
            "kneecapped for missing a payment deadline",
            "poisoned by a business rival — slow-acting, they nearly didn't notice",
            "broke both arms falling from a Warrens rooftop while fleeing Wardens",
            "throat-cut by a competitor, bled out in an alley — found by Saints volunteers",
            # Rift exposure (now just one possibility among many)
            "too close when a micro-Rift opened — partial reality burn",
            "Rift residue exposure from an inadequately sealed sample",
            "caught in a Rift surge in the Outer Wall sector, minor warping",
        ])
        injury_bulletin = await _generate(
            f"{_LORE}\nNPC: {npc['name']}, {npc.get('faction', 'Independent')}, {npc.get('rank', 'Member')}.\n"
            f"Injury cause: {_injury_cause}.\n"
            f"Write a 2-3 line Undercity bulletin reporting this injury. Terse. Real. Outcome uncertain.\n"
            f"Use the specific cause above — do not default to 'Rift exposure' or generic fantasy.\n"
            f"No preamble. Output only the bulletin."
        )

        if injury_bulletin and channel:
            embed = discord.Embed(
                description=injury_bulletin,
                color=discord.Color.orange()
            )
            embed.set_footer(text=f"🩹 {npc['name']} · {npc.get('faction', '?')} · {npc.get('rank', '?')}")
            await channel.send(embed=embed)

        await asyncio.sleep(5)

    logger.info(
        f"🧬 Lifecycle complete. {len(npcs)} NPCs total, {len(alive_npcs)} alive, "
        f"{len(injured_npcs)} recovering, {len(injury_targets)} newly injured today."
    )

    # --- Graveyard Events: super rare resurrection / undead / doppelganger ---
    graveyard = _load_graveyard()
    if graveyard:
        logger.info(f"🪦 Checking graveyard events ({len(graveyard)} dead NPCs)...")
        try:
            await _check_graveyard_events(channel)
        except Exception as e:
            logger.warning(f"🪦 Graveyard event error: {e}")


# ---------------------------------------------------------------------------
# Graveyard Events — super rare events for dead NPCs
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Faction Leaders — tagged for special death handling
# ---------------------------------------------------------------------------

FACTION_LEADERS = {
    "Iron Fang Consortium":   "Serrik Dhal",
    "Argent Blades":          "Lady Cerys Valemont",
    "Wardens of Ash":         "Captain Havel Korin",
    "Serpent Choir":          "High Apostle Yzura",
    "Obsidian Lotus":         "The Widow",
    "Glass Sigil":            "Senior Archivist Pell",
    "Patchwork Saints":       "Pol Greaves",       # informal leader
    "Adventurers Guild":      "Mari Fen",
    "Guild of Ashen Scrolls": "Archivist Eir Velan",
    "Tower Authority":        "Director Myra Kess",
    "Wizards Tower":          "Yaulderna Silverstreak",
    "Brother Thane's Cult":   "Brother Thane",
}

# Reverse lookup: leader name -> faction
_LEADER_NAMES = {v.lower(): k for k, v in FACTION_LEADERS.items()}


def is_faction_leader(npc_name: str) -> bool:
    """Check if an NPC is a faction leader."""
    return npc_name.lower() in _LEADER_NAMES


def get_leader_faction(npc_name: str) -> Optional[str]:
    """Return the faction a leader leads, or None."""
    return _LEADER_NAMES.get(npc_name.lower())


# Leader death outcomes and weights
LEADER_DEATH_OUTCOMES = {
    "raise_dead":       0.40,  # 40% — comes back, same person, weakened
    "resurrection":     0.30,  # 30% — comes back changed (race/gender/personality shift)
    "tower_absorbed":   0.30,  # 30% — permanently gone, successor promoted
}


async def _handle_leader_death(dead_npc: dict, npcs: List[dict], channel) -> str:
    """Special handling when a faction leader dies.
    Returns the outcome type: 'raise_dead', 'resurrection', or 'tower_absorbed'."""
    import discord

    name    = dead_npc.get("name", "Unknown")
    faction = dead_npc.get("faction", "Independent")
    species = dead_npc.get("species", "Human")
    today   = datetime.now().strftime("%Y-%m-%d")

    # Roll for outcome
    roll = random.random()
    cumulative = 0.0
    outcome = "tower_absorbed"  # default fallback
    for otype, chance in LEADER_DEATH_OUTCOMES.items():
        cumulative += chance
        if roll <= cumulative:
            outcome = otype
            break

    graveyard = _load_graveyard()

    if outcome == "raise_dead":
        # === RAISE DEAD — comes back as themselves, weakened ===
        logger.info(f"\U0001f451 Leader death: {name} ({faction}) — RAISE DEAD")

        bulletin = await _generate(
            f"{_LORE}\n"
            f"FACTION LEADER: {name}, {species}, head of {faction}.\n"
            f"{name} was killed but the faction immediately invoked an emergency "
            f"resurrection contract with the Serpent Choir. Cost was enormous.\n"
            f"Write a 3-4 line urgent news bulletin. {name} is alive but visibly shaken.\n"
            f"The faction spent a fortune. Rivals are circling. {name} is not the same.\n"
            f"Tone: relief mixed with dread. Coming back from death has a price.\n"
            f"No preamble. Output only the bulletin."
        )

        dead_npc["status"] = "injured"
        dead_npc["history"].append(f"[{today}] KILLED AND RAISED. Faction emergency resurrection. Weakened.")
        dead_npc.pop("cause_of_death", None)
        dead_npc.pop("moved_to_graveyard_at", None)
        dead_npc["last_event_at"] = datetime.now().isoformat()
        dead_npc["oracle_notes"] = (
            dead_npc.get("oracle_notes", "") +
            " Died and was raised. Carries death-trauma. The faction paid dearly. Rivals smell weakness."
        ).strip()

        npcs.append(dead_npc)
        _save_npcs(npcs)
        graveyard = [g for g in graveyard if g.get("name") != name]
        _save_graveyard(graveyard)

        if bulletin and channel:
            embed = discord.Embed(description=bulletin, color=0x33CC77)
            embed.set_footer(text=f"\U0001f451 Raise Dead \u00b7 {name} \u00b7 {faction} Leader \u00b7 RESTORED")
            await channel.send(embed=embed)

    elif outcome == "resurrection":
        # === RESURRECTION — comes back CHANGED (different race/gender/personality) ===
        logger.info(f"\U0001f451 Leader death: {name} ({faction}) — RESURRECTION (changed)")

        new_species = random.choice([s for s in SPECIES_LIST if s != species])
        gender_flip = random.random() < 0.4  # 40% chance gender changes too
        personality_shift = random.choice([
            "quieter, more cautious, haunted by what they experienced",
            "harder, colder, ruthlessly pragmatic where they were once measured",
            "erratic, prone to strange decisions, as if listening to something no one else hears",
            "warmer, more empathetic, as if death showed them what mattered",
            "paranoid, trusting no one, convinced someone arranged their death",
        ])

        gender_note = ""
        if gender_flip:
            old_gender = "male" if random.random() < 0.5 else "female"
            new_gender = "female" if old_gender == "male" else "male"
            gender_note = f" Their gender has shifted from {old_gender} to {new_gender} \u2014 the magic was imperfect."

        bulletin = await _generate(
            f"{_LORE}\n"
            f"FACTION LEADER: {name}, formerly {species}, head of {faction}.\n"
            f"{name} was killed and resurrected, but the magic was imperfect.\n"
            f"They returned as {new_species} instead of {species}.{gender_note}\n"
            f"Their personality has shifted: {personality_shift}\n"
            f"Write a 3-4 line unsettling news bulletin. The city recognises them but "
            f"something is clearly different. Their faction is divided on whether this "
            f"is really {name}.\n"
            f"Tone: uncanny, specific, grounded.\n"
            f"No preamble. Output only the bulletin."
        )

        dead_npc["status"] = "alive"
        dead_npc["species"] = f"{new_species} (formerly {species})"
        dead_npc["history"].append(
            f"[{today}] KILLED AND RESURRECTED \u2014 returned as {new_species}. "
            f"Personality shifted: {personality_shift}.{' Gender changed.' if gender_flip else ''}"
        )
        dead_npc.pop("cause_of_death", None)
        dead_npc.pop("moved_to_graveyard_at", None)
        dead_npc["last_event_at"] = datetime.now().isoformat()
        dead_npc["oracle_notes"] = (
            dead_npc.get("oracle_notes", "") +
            f" Resurrected imperfectly. Now {new_species}. {personality_shift.capitalize()}. "
            f"The Oracle questions whether this is truly the same soul."
        ).strip()
        dead_npc["motivation"] = (
            dead_npc.get("motivation", "") +
            f" Since resurrection: {personality_shift}."
        ).strip()

        npcs.append(dead_npc)
        _save_npcs(npcs)
        graveyard = [g for g in graveyard if g.get("name") != name]
        _save_graveyard(graveyard)

        if bulletin and channel:
            embed = discord.Embed(description=bulletin, color=0xCC6600)
            embed.set_footer(text=f"\U0001f451 Imperfect Resurrection \u00b7 {name} \u00b7 Now {new_species} \u00b7 CHANGED")
            await channel.send(embed=embed)

    else:
        # === TOWER ABSORBED — permanently gone, successor promoted ===
        logger.info(f"\U0001f451 Leader death: {name} ({faction}) \u2014 TOWER ABSORBED (permanent)")

        # Find the highest-ranked same-faction NPC to promote
        faction_members = [
            n for n in npcs
            if n.get("faction") == faction
            and n.get("status") in ("alive", "injured")
            and n.get("name") != name
        ]

        successor = None
        successor_name = "no one"
        if faction_members:
            ranks = FACTION_RANKS.get(faction, [])
            rank_order = {r: i for i, r in enumerate(ranks)}

            def rank_score(npc):
                return rank_order.get(npc.get("rank", ""), -1)

            faction_members.sort(key=rank_score, reverse=True)
            successor = faction_members[0]
            successor_name = successor.get("name", "Unknown")

            # Promote successor to top rank
            old_rank = successor.get("rank", "?")
            top_rank = ranks[-1] if ranks else "Leader"
            successor["rank"] = top_rank
            successor["history"].append(
                f"[{today}] PROMOTED to {top_rank} of {faction} following the permanent loss of {name}."
            )
            successor["oracle_notes"] = (
                successor.get("oracle_notes", "") +
                f" Suddenly thrust into leadership after {name}'s permanent death. The faction is in transition."
            ).strip()
            successor["last_event_at"] = datetime.now().isoformat()
            _save_npcs(npcs)

            # Update FACTION_LEADERS
            FACTION_LEADERS[faction] = successor_name
            _LEADER_NAMES[successor_name.lower()] = faction

            logger.info(f"\U0001f451 {successor_name} promoted to lead {faction} (was {old_rank})")

        successor_line = (
            f"Successor: {successor_name} has been elevated to lead {faction}."
            if successor else
            "The faction has no clear successor. Internal power struggle imminent."
        )
        successor_detail = (
            f"Mention {successor_name} stepping up \u2014 are they ready? Does the faction trust them?"
            if successor else
            "Multiple candidates are already positioning. This could get ugly."
        )
        bulletin = await _generate(
            f"{_LORE}\n"
            f"FACTION LEADER: {name}, {species}, head of {faction}. PERMANENTLY DEAD.\n"
            f"The Tower has absorbed {name}'s soul. There is no coming back.\n"
            f"{successor_line}\n"
            f"Write a 4-5 line solemn, significant news bulletin. This is a major city event.\n"
            f"The faction is shaken. Rivals see opportunity. The city holds its breath.\n"
            f"{successor_detail}\n"
            f"Tone: grave, consequential, specific. A power vacuum just opened.\n"
            f"No preamble. Output only the bulletin."
        )

        # Mark as permanently absorbed in graveyard
        dead_npc["history"].append(f"[{today}] TOWER ABSORBED \u2014 soul claimed permanently. No resurrection possible.")
        dead_npc["tower_absorbed"] = True
        _save_graveyard(graveyard)

        if bulletin and channel:
            embed = discord.Embed(description=bulletin, color=0x1a1a2e)
            footer_text = f"\U0001f480 Tower Absorbed \u00b7 {name} \u00b7 PERMANENTLY LOST"
            if successor:
                footer_text += f" \u00b7 {successor_name} now leads {faction}"
            embed.set_footer(text=footer_text)
            await channel.send(embed=embed)

    return outcome


# Per dead NPC per lifecycle tick. These are VERY rare.
GRAVEYARD_EVENT_CHANCES = {
    "tower_fund_me":  0.01,   # 1% — community raises funds, NPC resurrected properly
    "undead_return":  0.01,   # 1% — comes back wrong (undead, changed, dangerous)
    "doppelganger":   0.02,   # 2% — someone is impersonating the dead NPC
}


async def _check_graveyard_events(channel) -> None:
    """Roll for rare events involving dead NPCs in the graveyard.
    At most ONE event fires per lifecycle cycle to keep things special."""
    import discord

    graveyard = _load_graveyard()
    if not graveyard:
        return

    npcs = _load_npcs()
    today = datetime.now().strftime("%Y-%m-%d")
    event_fired = False

    # Shuffle so it's not always the first dead NPC that gets checked first
    random.shuffle(graveyard)

    for dead_npc in graveyard:
        if event_fired:
            break

        name    = dead_npc.get("name", "Unknown")
        faction = dead_npc.get("faction", "Independent")
        species = dead_npc.get("species", "Human")

        # Skip tower-absorbed NPCs — they're permanently gone
        if dead_npc.get("tower_absorbed"):
            continue

        # Skip NPCs that died very recently (give them at least 3 days in the ground)
        moved_at = dead_npc.get("moved_to_graveyard_at", "")
        if moved_at:
            try:
                days_dead = (datetime.now() - datetime.fromisoformat(moved_at)).total_seconds() / 86400
                if days_dead < 3:
                    continue
            except Exception:
                pass

        # LEADERS get special handling — automatic, not random
        if is_faction_leader(name):
            logger.info(f"\U0001f451 Faction leader {name} found in graveyard — triggering leader death protocol")
            try:
                await _handle_leader_death(dead_npc, npcs, channel)
            except Exception as e:
                logger.error(f"\U0001f451 Leader death handling failed for {name}: {e}")
            event_fired = True
            break

        # Roll for each event type (normal NPCs)
        roll = random.random()
        cumulative = 0.0

        for event_type, chance in GRAVEYARD_EVENT_CHANCES.items():
            cumulative += chance
            if roll > cumulative:
                continue

            # === TOWER FUND ME — Community resurrection ===
            if event_type == "tower_fund_me":
                logger.info(f"💰 GRAVEYARD EVENT: Tower Fund Me for {name}!")

                bulletin = await _generate(
                    f"{_LORE}\n"
                    f"DEAD NPC: {name}, {species}, formerly {faction}.\n"
                    f"A community fundraising campaign called 'Tower Fund Me' has raised enough "
                    f"Kharma and EC to hire a Serpent Choir resurrection contract for {name}.\n"
                    f"Write a 3-4 line news bulletin about the successful resurrection. "
                    f"Include: who organized it, how much it cost (use a large Kharma amount), "
                    f"the Serpent Choir's involvement, and {name}'s confused first words.\n"
                    f"{name} is alive but weakened — they'll need time to recover.\n"
                    f"Tone: hopeful but with an edge. Resurrection has consequences in this world.\n"
                    f"No preamble. Output only the bulletin."
                )

                # Move NPC back to active roster
                dead_npc["status"] = "injured"  # comes back weak
                dead_npc["history"].append(f"[{today}] RESURRECTED via Tower Fund Me campaign. Weakened but alive.")
                dead_npc.pop("cause_of_death", None)
                dead_npc.pop("moved_to_graveyard_at", None)
                dead_npc["last_event_at"] = datetime.now().isoformat()
                dead_npc["oracle_notes"] = (
                    dead_npc.get("oracle_notes", "") +
                    " Recently resurrected — disoriented, weakened, and carrying the weight of what they saw on the other side."
                ).strip()

                npcs.append(dead_npc)
                _save_npcs(npcs)

                # Remove from graveyard
                graveyard = [g for g in graveyard if g.get("name") != name]
                _save_graveyard(graveyard)

                if bulletin and channel:
                    embed = discord.Embed(
                        description=bulletin,
                        color=0x33CC77,  # green — good news
                    )
                    embed.set_footer(text=f"💰 Tower Fund Me · {name} · RESURRECTED")
                    await channel.send(embed=embed)

                event_fired = True

            # === UNDEAD RETURN — Comes back wrong ===
            elif event_type == "undead_return":
                logger.info(f"🧟 GRAVEYARD EVENT: Undead return for {name}!")

                # Pick a transformation type
                undead_type = random.choice([
                    ("Revenant", "burning with purpose, hollow-eyed, driven by unfinished business"),
                    ("Wight", "cold, calculating, remembers everything but feels nothing"),
                    ("Ghost", "translucent, flickering, trapped between the city and whatever comes after"),
                    ("Zombie (intelligent)", "rotting but lucid — the worst kind, because they know what they've become"),
                    ("Death Knight", "armored in shadow, wielding dark echoes of their former skills"),
                ])
                utype, udesc = undead_type

                bulletin = await _generate(
                    f"{_LORE}\n"
                    f"DEAD NPC: {name}, formerly {species}, {faction}.\n"
                    f"{name} has returned from death as a {utype}: {udesc}.\n"
                    f"Write a 3-4 line alarming news bulletin about {name} being sighted in the Undercity.\n"
                    f"They were seen near their old haunts. Witnesses are terrified.\n"
                    f"The faction they belonged to is [reacting: horror, denial, or trying to recruit them].\n"
                    f"Tone: unsettling, urgent, specific. This is not normal.\n"
                    f"No preamble. Output only the bulletin."
                )

                # Move back to roster as an undead NPC
                dead_npc["status"] = "alive"
                dead_npc["species"] = f"{utype} (formerly {species})"
                dead_npc["history"].append(f"[{today}] RETURNED FROM DEATH as {utype}. {udesc}.")
                dead_npc.pop("cause_of_death", None)
                dead_npc.pop("moved_to_graveyard_at", None)
                dead_npc["last_event_at"] = datetime.now().isoformat()
                dead_npc["oracle_notes"] = (
                    dead_npc.get("oracle_notes", "") +
                    f" Returned from death as {utype}. Changed. Dangerous. The Oracle watches with great interest."
                ).strip()
                dead_npc["motivation"] = f"Unfinished business from before death. Driven by {random.choice(['vengeance', 'regret', 'a promise they never kept', 'something they saw on the other side', 'hunger for what they lost'])}."

                npcs.append(dead_npc)
                _save_npcs(npcs)

                graveyard = [g for g in graveyard if g.get("name") != name]
                _save_graveyard(graveyard)

                if bulletin and channel:
                    embed = discord.Embed(
                        description=bulletin,
                        color=0x660066,  # dark purple — supernatural
                    )
                    embed.set_footer(text=f"🧟 {name} · {utype} · RETURNED FROM DEATH")
                    await channel.send(embed=embed)

                event_fired = True

            # === DOPPELGANGER — Someone is impersonating the dead NPC ===
            elif event_type == "doppelganger":
                logger.info(f"🎭 GRAVEYARD EVENT: Doppelganger of {name}!")

                bulletin = await _generate(
                    f"{_LORE}\n"
                    f"DEAD NPC: {name}, formerly {species}, {faction}. CONFIRMED DEAD.\n"
                    f"Multiple witnesses have reported seeing someone who looks exactly like {name} "
                    f"in the Undercity. But {name} is dead.\n"
                    f"Write a 3-4 line disturbing news bulletin about these sightings.\n"
                    f"Include: where they were seen, who reported it, and why people are unsettled.\n"
                    f"The impersonator was seen doing something {name} used to do — "
                    f"visiting their old haunts, talking to their old contacts.\n"
                    f"Is it a shapeshifter? A twin? A Rift echo? Nobody knows.\n"
                    f"Tone: creepy, specific, grounded. No resolution — just the unsettling report.\n"
                    f"No preamble. Output only the bulletin."
                )

                # Add to dead NPC's graveyard history (they stay dead)
                dead_npc["history"].append(f"[{today}] Doppelganger sighting — someone impersonating {name} spotted in the Undercity.")
                _save_graveyard(graveyard)

                if bulletin and channel:
                    embed = discord.Embed(
                        description=bulletin,
                        color=0xAA6633,  # brown — mystery
                    )
                    embed.set_footer(text=f"🎭 Doppelganger · {name} · IDENTITY UNKNOWN")
                    await channel.send(embed=embed)

                # Generate a mission for the doppelganger investigation
                try:
                    from src.mission_board import _generate as _gen_mission, _parse_mission, _add_mission, _expiry_for_tier

                    mission_prompt = f"""{_LORE}

---
Generate ONE investigation mission about a doppelganger impersonating the deceased {name} ({species}, {faction}).
Someone or something is walking the Undercity wearing {name}'s face. They were confirmed dead.
The posting faction should be {faction} (they want answers about their dead member) or the Adventurers Guild.

REQUIRED FORMAT:

**[FACTION NAME] — MISSION TITLE**
*Tier: investigation | Expires: TBD | Reward: [X EC + any extras]*
*Opposes: None*

[2-3 sentences. Specific sighting locations, named witnesses, clear objective: find and identify the impersonator.]

*Contact: [named NPC], [location]*

RULES:
- Tier must be investigation
- Make it feel creepy and personal — this is someone wearing a dead person's face
- No preamble, no sign-off. Output the mission post only."""

                    mission_text = await _gen_mission(mission_prompt)
                    if mission_text:
                        mission = _parse_mission(mission_text)
                        mission["doppelganger_of"] = name
                        _add_mission(mission)
                        logger.info(f"🎭 Doppelganger mission created: {mission.get('title', '?')}")
                except Exception as e:
                    logger.warning(f"🎭 Doppelganger mission creation failed: {e}")

                event_fired = True

            break  # Only one event type per NPC per cycle

    if event_fired:
        logger.info("🪦 Graveyard event processed this cycle")


# ---------------------------------------------------------------------------
# Interval
# ---------------------------------------------------------------------------

def next_lifecycle_seconds() -> int:
    """20-28 hours so it doesn't fire at the exact same time every day."""
    return random.randint(20 * 3600, 28 * 3600)
