"""
party_interview.py — Post-mission party interviews with business sponsorships.

Triggered on mission completion when the outcome is epic enough.
Interview runs in Discord for 7 days, then archives into the research corpus
so future mission/world generation can reference past heroics.

Flow:
    maybe_trigger_interview(outcome, mission, discord_client)
        → score_epic() — must hit threshold
        → pick_sponsor() — business or faction sponsor
        → generate_interview() — Ollama Q&A debrief
        → post to Discord embed
        → save to party_interviews table (expires in 7 days)

Archival (called from self_learning._study_archive_interviews):
    archive_expired_interviews()
        → fetch expired rows, append to global_state['interview_archive']
        → mark archived in DB
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, timedelta
from typing import Optional

import discord
import httpx

from src.log import logger

OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

# Tiers that always trigger an interview
_INTERVIEW_TIERS = {"epic", "divine"}

# Delay before posting so it doesn't drown the completion notice
_POST_DELAY_SECONDS = 90

# Fallback reporters if we want variety
_REPORTERS = [
    "Undercity Correspondent",
    "Guild Bulletin Reporter",
    "The Tower Dispatch",
    "Mira Voss, Staff Reporter",
    "The Daily Dome",
    "Field Correspondent — Adventurers Beat",
]


# ── Tier check ────────────────────────────────────────────────────────────────

def score_epic(outcome: dict) -> int:
    """Return a simple richness score used only for embed colour — tier drives the trigger."""
    score = 0
    if outcome.get("notable_moments", "").strip():  score += 3
    if outcome.get("npcs_killed", "").strip():       score += 2
    if outcome.get("key_decisions", "").strip():     score += 2
    if outcome.get("loose_threads", "").strip():     score += 1
    if outcome.get("location_changes", "").strip():  score += 1
    return score


def _should_interview(outcome: dict) -> bool:
    """Interview triggers on epic or divine tier missions only."""
    tier = str(outcome.get("tier") or "").lower().strip()
    return tier in _INTERVIEW_TIERS


# ── Sponsor selection ─────────────────────────────────────────────────────────

def pick_sponsor(party_profile: Optional[dict]) -> dict:
    """
    Pick a business sponsor for this interview.
    Priority: party's existing sponsor → generated shop ads → gazetteer small shops → fallback.
    """
    from src.db_api import raw_query, get_global_state

    # 1. Use party's existing sponsor if set
    if party_profile:
        existing = party_profile.get("sponsor") or party_profile.get("profile_json", {})
        if isinstance(existing, dict):
            existing = existing.get("sponsor")
        if existing and existing not in ("No Affiliation", "None", "null", ""):
            return {
                "shop_name":  str(existing),
                "district":   party_profile.get("affiliation", "the Undercity"),
                "tagline":    "— proud patron of the Guild's finest.",
                "ad_type":    "faction",
            }

    # 2. Pull from nightly-generated shop/tourism ads
    try:
        generated = get_global_state("generated_ads") or []
        if isinstance(generated, str):
            generated = json.loads(generated)
        shops = [a for a in generated if a.get("ad_type") in ("shop", "tourism") and a.get("shop_name")]
        if shops:
            pick = random.choice(shops)
            return {
                "shop_name":  pick["shop_name"],
                "district":   pick.get("district", "the Undercity"),
                "tagline":    pick.get("ad_text", "")[:80].rstrip(".") + ".",
                "ad_type":    "shop",
            }
    except Exception:
        pass

    # 3. Fall back to a random gazetteer small shop
    try:
        rows = raw_query(
            "SELECT name, district, description FROM gazetteer_places "
            "WHERE place_type = 'small_shop' ORDER BY RAND() LIMIT 1"
        ) or []
        if rows:
            r = rows[0]
            return {
                "shop_name":  r["name"],
                "district":   r.get("district", "the Undercity"),
                "tagline":    str(r.get("description") or "Serving the Undercity with pride.")[:80],
                "ad_type":    "shop",
            }
    except Exception:
        pass

    # 4. Generic fallback
    return {
        "shop_name":  "The Undercity Outfitters",
        "district":   "Grand Forum",
        "tagline":    "Everything an adventurer needs, nothing they don't.",
        "ad_type":    "shop",
    }


# ── Interview generation ──────────────────────────────────────────────────────

async def _ask_ollama(prompt: str, system: str = "", timeout: int = 180) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        from src.resource_cop import wait_for_ollama_turn
        decision = await wait_for_ollama_turn("party_interview", track="primary", max_wait_seconds=60)
        if not decision.run_now:
            logger.info(f"party_interview: Ollama deferred by resource cop: {decision.reason}")
            return ""
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
            })
            return resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.warning(f"party_interview: Ollama call failed: {e}")
        return ""


async def generate_interview(
    outcome: dict,
    party_profile: Optional[dict],
    sponsor: dict,
) -> str:
    """Generate an interview Q&A debrief via Ollama. Returns formatted text."""

    party_name  = (party_profile or {}).get("name") or outcome.get("completed_by", "Unknown Party")
    members     = (party_profile or {}).get("members") or []
    member_desc = ""
    if members:
        member_desc = "Party members:\n" + "\n".join(
            f"  - {m.get('name','?')} ({m.get('role','?')}, {m.get('species','?')}): {m.get('note','')}"
            for m in members[:6]
        )

    mission_context = "\n".join(filter(None, [
        f"Mission: {outcome.get('mission_title', 'Unknown')}",
        f"Result: {outcome.get('result', 'completed').upper()}",
        f"Faction: {outcome.get('faction', '')}",
        f"Opposing: {outcome.get('opposing_faction', '')}",
        f"Killed/Removed: {outcome.get('npcs_killed', '')}",
        f"Key decisions: {outcome.get('key_decisions', '')}",
        f"Location changes: {outcome.get('location_changes', '')}",
        f"Notable moments: {outcome.get('notable_moments', '')}",
        f"Loose threads: {outcome.get('loose_threads', '')}",
    ]))

    prompt = f"""You write post-mission interview dispatches for the Guild Bulletin — the Undercity's adventuring-contract noticeboard.

MISSION DEBRIEF DATA:
{mission_context}

PARTY: {party_name}
{member_desc}

SPONSOR: {sponsor['shop_name']} ({sponsor['district']}) — "{sponsor['tagline']}"

Write a short interview (4-6 Q&A exchanges, ~350 words total) in this format:

---
*[Reporter's name from: {', '.join(_REPORTERS)}] catches up with {party_name} at [specific Undercity location] shortly after their return.*

**Q: [Question to the party as a whole or a specific member]**
**[Member name or "The party"]:** [Answer — honest, specific, in character. Mix bravado, exhaustion, dark humor, or professional detachment. Reference actual events from the debrief.]

[repeat for 4-6 exchanges]

*[Closing line from the reporter — 1 sentence summarising the party's mood or status]*

---
*This debrief was brought to you by **{sponsor['shop_name']}** — {sponsor['tagline']}*
---

Rules:
- Reference specific details from the mission debrief (not vague generalities)
- Named members should sound distinct — different personalities, reactions
- The Undercity tone: gritty, specific, noir-urban-fantasy. Not heroic-epic.
- If notable_moments is blank, infer drama from other fields
- No meta-commentary. No "as an AI". Just the interview text.

Output ONLY the interview text, nothing else."""

    return await _ask_ollama(
        prompt,
        system="You are a gritty in-world journalist. Write only the interview, no preamble.",
        timeout=180,
    )


# ── Discord posting ───────────────────────────────────────────────────────────

def _build_embed(
    interview_text: str,
    sponsor: dict,
    outcome: dict,
    party_name: str,
    epic_score: int,
) -> discord.Embed:
    title = f"🎙️ DEBRIEF: {outcome.get('mission_title', 'Contract Complete')}"
    tier_str = outcome.get("tier", "")

    embed = discord.Embed(
        title=title,
        description=interview_text[:4000],
        color=discord.Color.gold() if epic_score >= 7 else discord.Color.teal(),
    )
    embed.set_footer(text=(
        f"📋 {party_name} | {tier_str} | "
        f"Sponsored by {sponsor['shop_name']} · {sponsor['district']}"
    ))
    embed.timestamp = datetime.utcnow()
    return embed


async def _get_interview_channel(discord_client) -> Optional[discord.TextChannel]:
    """Resolve the channel to post interviews to."""
    for env_key in ("INTERVIEW_CHANNEL_ID", "MISSION_RESULTS_CHANNEL_ID", "DISCORD_CHANNEL_ID"):
        raw = os.getenv(env_key, "").strip()
        if raw:
            try:
                ch = discord_client.get_channel(int(raw))
                if ch:
                    return ch
            except Exception:
                pass
    return None


# ── Save / archive ────────────────────────────────────────────────────────────

def _save_interview(
    outcome: dict,
    party_name: str,
    sponsor: dict,
    interview_text: str,
    message_id: Optional[str],
    epic_score: int,
) -> None:
    from src.db_api import raw_execute
    expires = datetime.now() + timedelta(days=7)
    raw_execute(
        """INSERT INTO party_interviews
           (mission_title, party_name, sponsor_name, sponsor_district,
            interview_text, discord_message_id, epic_score, expires_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            outcome.get("mission_title", ""),
            party_name,
            sponsor.get("shop_name", ""),
            sponsor.get("district", ""),
            interview_text,
            str(message_id) if message_id else None,
            epic_score,
            expires,
        ),
    )


def archive_expired_interviews() -> int:
    """
    Called from self_learning nightly.
    Fetches interviews past their 7-day window, appends to global_state['interview_archive'],
    and marks them archived. Returns count archived.
    """
    from src.db_api import raw_query, raw_execute, get_global_state, set_global_state

    expired = raw_query(
        "SELECT id, mission_title, party_name, sponsor_name, interview_text, epic_score "
        "FROM party_interviews WHERE archived = 0 AND expires_at < NOW()"
    ) or []

    if not expired:
        return 0

    archive = get_global_state("interview_archive") or []
    if isinstance(archive, str):
        try: archive = json.loads(archive)
        except: archive = []

    for row in expired:
        archive.append({
            "mission_title": row.get("mission_title", ""),
            "party_name":    row.get("party_name", ""),
            "sponsor":       row.get("sponsor_name", ""),
            "epic_score":    row.get("epic_score", 0),
            "text":          (row.get("interview_text") or "")[:2000],
            "archived_at":   datetime.now().isoformat(),
        })
        raw_execute(
            "UPDATE party_interviews SET archived=1, archived_at=NOW() WHERE id=%s",
            (row["id"],),
        )

    # Keep last 100 in global_state
    archive = archive[-100:]
    set_global_state("interview_archive", archive)
    return len(expired)


# ── Main entry point ──────────────────────────────────────────────────────────

async def maybe_trigger_interview(
    outcome: dict,
    mission: dict,
    discord_client,
) -> None:
    """
    Async task — triggered after mission completion.
    Scores the mission; if epic enough, generates and posts a sponsored interview.
    """
    try:
        epic_score = score_epic(outcome)
        if not _should_interview(outcome):
            logger.debug(f"party_interview: skipped ({outcome.get('mission_title','?')}, score={epic_score})")
            return

        party_name = outcome.get("completed_by", "Unknown Party")

        # Load party profile for member names
        party_profile = None
        try:
            from src.party_profiles import load_profile
            party_profile = load_profile(party_name)
        except Exception:
            pass

        sponsor = pick_sponsor(party_profile)

        # Wait so the interview doesn't drown the completion notice
        await asyncio.sleep(_POST_DELAY_SECONDS)

        interview_text = await generate_interview(outcome, party_profile, sponsor)
        if not interview_text:
            logger.warning(f"party_interview: Ollama returned empty for {party_name}")
            return

        channel = await _get_interview_channel(discord_client)
        message_id = None

        if channel:
            try:
                embed = _build_embed(interview_text, sponsor, outcome, party_name, epic_score)
                msg = await channel.send(embed=embed)
                message_id = str(msg.id)
                logger.info(
                    f"🎙️ Interview posted: {party_name} — {outcome.get('mission_title','?')} "
                    f"(score={epic_score}, sponsor={sponsor['shop_name']})"
                )
            except Exception as e:
                logger.warning(f"party_interview: Discord post failed: {e}")

        _save_interview(outcome, party_name, sponsor, interview_text, message_id, epic_score)

    except Exception as e:
        logger.exception(f"party_interview: unexpected error: {e}")
