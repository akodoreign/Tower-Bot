"""
bounty_board.py — Undercity Wanted / Bounty System

Rare wanted postings on the mission board.
Only four entities can officially issue bounties:
  - Wardens of Ash
  - Adventurers Guild
  - Grand Forum (civic authority)
  - FTA / Tower Authority

Other factions route through one of these four.
Max one bounty bulletin per 7 real days.
Bounty posts live on the mission board channel alongside missions.
Tied to news feed — a news bulletin fires when a bounty is posted.

Persists to campaign_docs/bounty_board.json
"""

from __future__ import annotations
import json, os, random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from src.log import logger

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
BOUNTY_FILE   = DOCS_DIR / "bounty_board.json"
TOWER_YEAR_OFFSET = 10

# Only these four can officially post bounties
BOUNTY_ISSUERS = [
    "Wardens of Ash",
    "Adventurers Guild",
    "Grand Forum Authority",
    "FTA / Tower Authority",
]

# Other factions post through one of the four — show both
PROXY_FACTIONS = {
    "Iron Fang Consortium":    "Adventurers Guild",
    "Argent Blades":           "Adventurers Guild",
    "Serpent Choir":           "Grand Forum Authority",
    "Obsidian Lotus":          "Wardens of Ash",       # reluctantly
    "Glass Sigil":             "FTA / Tower Authority",
    "Patchwork Saints":        "Grand Forum Authority",
    "Guild of Ashen Scrolls":  "Grand Forum Authority",
    "Brother Thane's Cult":    "Wardens of Ash",        # involuntary — Wardens post it
}

# One bounty max per this many seconds (7 days)
BOUNTY_COOLDOWN = 7 * 24 * 3600

# Bounties expire after 14-60 days
BOUNTY_EXPIRY_MIN = 14
BOUNTY_EXPIRY_MAX = 60

_BOUNTY_SUBJECTS = [
    # (subject_hint, crime_hint, reward_min, reward_max)
    ("a disgraced Warden deserter",         "abandoning post during a Rift event",         18_000,  45_000),
    ("an unlicensed relic dealer",          "selling unregistered arcane artefacts",        12_000,  30_000),
    ("a memory-thief operating in Warrens", "non-consensual memory extraction",             25_000,  60_000),
    ("a Serpent Choir contract defaulter",  "breach of divine contract terms",              30_000,  80_000),
    ("an Iron Fang embezzler",              "siphoning Consortium funds",                   40_000, 100_000),
    ("a Rift-harvester",                    "illegal collection of Rift residue for resale",22_000,  55_000),
    ("a forged-license adventurer",         "operating under a falsified FTA rank",         15_000,  35_000),
    ("a cult recruiter",                    "aggressive recruitment violating district codes",10_000, 28_000),
    ("a poisoner operating in the Markets", "contaminating food supply in Markets Infinite", 35_000,  90_000),
    ("a body-broker",                       "trafficking in Kharma-stripped corpses",        50_000, 120_000),
    ("an escaped FTA detainee",             "breach of Tower Authority custody",            20_000,  50_000),
    ("a saboteur targeting the Outer Wall", "deliberate structural damage near Dome seals", 45_000, 110_000),
    ("a rogue Glass Sigil archivist",       "leaking classified Rift data to outside parties",28_000, 65_000),
    ("a Kharma counterfeiter",              "producing fraudulent faith-currency",           32_000,  75_000),
]

_CAPTURE_CONDITIONS = [
    "Wanted alive. Alive pays full reward. Dead pays half.",
    "Wanted for questioning. Must be delivered intact and coherent.",
    "Dead or alive. The issuing authority has stopped caring which.",
    "Alive only. Evidence must be preserved. Do not improvise.",
    "Alive preferred. Reward reduced 40% for non-viable delivery.",
    "Capture only — no termination authorised. FTA will audit outcomes.",
]


def _load_bounties() -> List[Dict]:
    if not BOUNTY_FILE.exists():
        return []
    try:
        return json.loads(BOUNTY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_bounties(bounties: List[Dict]) -> None:
    try:
        BOUNTY_FILE.write_text(json.dumps(bounties, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"Bounty save error: {e}")


def _last_bounty_posted_at() -> Optional[datetime]:
    bounties = _load_bounties()
    posted = [b for b in bounties if b.get("posted_at")]
    if not posted:
        return None
    try:
        return max(datetime.fromisoformat(b["posted_at"]) for b in posted)
    except Exception:
        return None


def should_post_bounty() -> bool:
    """True if 7+ days since last bounty and random roll passes (15% per bulletin tick)."""
    last = _last_bounty_posted_at()
    if last:
        elapsed = (datetime.now() - last).total_seconds()
        if elapsed < BOUNTY_COOLDOWN:
            return False
    # Even when eligible, only 15% chance per tick so it feels organic
    return random.random() < 0.15


async def generate_bounty_post(ollama_model: str, ollama_url: str) -> Optional[Dict]:
    """Ask Ollama to write a full bounty posting. Returns dict with post text + metadata."""
    import httpx, re

    subject_hint, crime_hint, reward_min, reward_max = random.choice(_BOUNTY_SUBJECTS)
    reward     = random.randint(reward_min, reward_max)
    capture    = random.choice(_CAPTURE_CONDITIONS)
    days       = random.randint(BOUNTY_EXPIRY_MIN, BOUNTY_EXPIRY_MAX)
    expires_dt = datetime.now() + timedelta(days=days)

    # Pick issuer — sometimes a proxy faction routes through an official issuer
    if random.random() < 0.4:
        proxy_faction  = random.choice(list(PROXY_FACTIONS.keys()))
        official_issuer = PROXY_FACTIONS[proxy_faction]
        issuer_line    = f"Issued by: {official_issuer} on behalf of {proxy_faction}"
        issuer_meta    = official_issuer
        proxy_meta     = proxy_faction
    else:
        issuer_meta    = random.choice(BOUNTY_ISSUERS)
        issuer_line    = f"Issued by: {issuer_meta}"
        proxy_meta     = None

    prompt = f"""You are writing a wanted / bounty posting for the Undercity mission board.
The Undercity is a sealed dark-fantasy city under a Dome. Currency is Essence Coins (EC).

Generate ONE bounty posting. Invent a specific named target — give them a name, a brief
physical description, last known location in the Undercity.

Subject hint: {subject_hint}
Alleged crime: {crime_hint}
Reward: {reward:,} EC
Capture condition: {capture}
{issuer_line}

REQUIRED OUTPUT FORMAT — output exactly this, nothing else:

🎯 **WANTED — [TARGET NAME]**
*{issuer_line}*

**Last known location:** [specific Undercity district or landmark]
**Description:** [2 sentences — physical appearance, distinguishing features, known behaviour]
**Alleged offence:** [1 sentence — specific and grounded]

**Reward:** {reward:,} EC  ·  *{capture}*

*[1 sentence of flavour — why this person is particularly dangerous, unusual, or hard to find.]*

RULES:
- Invent a specific named target. Make them feel real.
- Be specific about location, appearance, offence.
- Tone is official but terse — a board notice, not a story.
- No preamble, no sign-off. Output the bounty post only.
- If your response contains anything other than the bounty post, you have failed."""

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ollama_url, json={
                "model":    ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream":   False,
            })
            resp.raise_for_status()
            data = resp.json()

        text = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                text = msg.get("content", "").strip()

        # Strip preamble
        lines = text.splitlines()
        skip  = ("sure", "here's", "here is", "certainly", "of course", "below is", "absolutely")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        text = "\n".join(lines).strip()

        if not text:
            return None

        post_text = text + f"\n\n⏳ *Bounty active for {days} days. {expires_dt.strftime('%d %b %Y')}.*"

        return {
            "id":            f"bounty_{int(datetime.now().timestamp())}",
            "body":          post_text,
            "issuer":        issuer_meta,
            "proxy_faction": proxy_meta,
            "reward":        reward,
            "posted_at":     datetime.now().isoformat(),
            "expires_at":    expires_dt.isoformat(),
            "resolved":      False,
            "message_id":    None,
        }

    except Exception as e:
        logger.error(f"Bounty generation error: {e}")
        return None


def format_bounty_news_bulletin(bounty: Dict) -> str:
    """Short news bulletin that references the bounty post on the mission board."""
    issuer  = bounty.get("issuer", "an authority")
    proxy   = bounty.get("proxy_faction")
    reward  = bounty.get("reward", 0)

    proxy_line = f" (filed through {issuer} by {proxy})" if proxy else f" by {issuer}"
    now   = datetime.now()
    tower = now.replace(year=now.year + TOWER_YEAR_OFFSET)
    ts    = f"{now.strftime('%Y-%m-%d %H:%M')} │ Tower: {tower.strftime('%d %b %Y, %H:%M')}"

    return (
        f"-# 🕰️ {ts}\n"
        f"🎯 **BOUNTY POSTED** — A new wanted notice has been filed{proxy_line}. "
        f"Reward: **{reward:,} EC**. "
        f"*Full details on the mission board.*"
    )


async def check_bounty_expirations(channel) -> None:
    """Remove expired bounties from the board."""
    bounties = _load_bounties()
    now      = datetime.now()
    updated  = False

    for b in bounties:
        if b.get("resolved"):
            continue
        try:
            exp = datetime.fromisoformat(b["expires_at"])
        except Exception:
            continue
        if now >= exp:
            b["resolved"] = True
            updated = True
            # Try to delete the Discord message
            if b.get("message_id") and channel:
                try:
                    msg = await channel.fetch_message(b["message_id"])
                    await msg.delete()
                except Exception:
                    pass
            logger.info(f"🎯 Bounty expired: {b['id']}")

    if updated:
        _save_bounties(bounties)
