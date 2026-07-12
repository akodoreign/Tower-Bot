"""
novel_outline.py — Build a chapter-by-chapter outline for Bob to write from.

Uses DNDExpertAgent to produce a structured 18-25 chapter outline that maps
the mission's story beats to novel chapters. Each chapter entry has:
  - num:     chapter number
  - title:   chapter title
  - summary: 2-3 sentence plan for Bob to expand
  - pov:     which character's POV this chapter uses
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


async def build_novel_outline(ctx: dict, force: bool = True) -> list[dict]:
    """
    Generate a chapter-by-chapter outline for the novel.

    Returns list of dicts: {num, title, summary, pov}
    Falls back to a minimal outline if generation fails.
    """
    from src.agents.learning_agents import DNDExpertAgent

    title        = ctx["title"]
    faction      = ctx["faction"]
    tier         = ctx.get("tier", "standard")
    mission_body = ctx["body"]
    npc_block    = ctx["npc_block"]
    location     = ctx["primary_location"]
    mission_type = ctx.get("mission_type", "standard")
    personal_for = ctx.get("personal_for", "")
    char_info    = ctx.get("char_info", "")

    # Build protagonist block — critical so the outline names the right character
    if personal_for and char_info:
        protagonist_block = (
            f"PROTAGONIST (use this character throughout — do NOT invent a different one):\n"
            f"Name: {personal_for}\n"
            f"{char_info}\n\n"
            f"Every chapter should be written from {personal_for}'s perspective. "
            f"Use their name, race, class, and backstory in the outline summaries.\n\n"
        )
    elif personal_for:
        protagonist_block = (
            f"PROTAGONIST: {personal_for}\n"
            f"This mission is personal for {personal_for}. Every chapter centers on them. "
            f"Do NOT invent a different protagonist.\n\n"
        )
    else:
        protagonist_block = ""

    logger.info(f"[OUTLINE] Building novel outline for: {title!r} | protagonist: {personal_for or 'open party'}")

    expert = DNDExpertAgent()
    resp = None
    try:
        resp = await expert.complete(
            prompt=(
                f"Build a chapter-by-chapter outline for a full-length D&D fantasy novel.\n\n"
                f"MISSION: {title}\n"
                f"FACTION: {faction} | TIER: {tier} | TYPE: {mission_type}\n"
                f"LOCATION: {location}\n\n"
                + protagonist_block +
                f"MISSION BRIEF:\n{mission_body}\n\n"
                f"KEY NPCS:\n{npc_block}\n\n"
                "REQUIREMENTS:\n"
                "- 18 to 25 chapters\n"
                "- Target 70,000 to 100,000 words total (3,500-5,000 words per chapter)\n"
                "- Full three-act structure: setup (chs 1-6), rising action (chs 7-16), "
                "climax + resolution (chs 17-end)\n"
                "- Each chapter has a clear narrative purpose and ending beat\n"
                "- Characters introduced in Act 1 must have arcs that resolve by Act 3\n"
                "- Include at least one major twist per act\n\n"
                "Output ONLY valid JSON, no markdown fences:\n"
                "[\n"
                '  {"num": 1, "title": "Chapter Title", '
                '"summary": "2-3 sentence plan for this chapter", '
                f'"pov": "{personal_for or "Party"}"}},\n'
                "  ...\n"
                "]"
            ),
            force=force,
        )
    finally:
        await expert.close()

    if resp and resp.success and resp.content:
        # Strip markdown fences if present
        text = re.sub(r"```(?:json)?", "", resp.content).strip().rstrip("`").strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list) and len(parsed) >= 10:
                outline = [
                    {
                        "num":     int(c.get("num", i + 1)),
                        "title":   str(c.get("title", f"Chapter {i + 1}")),
                        "summary": str(c.get("summary", "")),
                        "pov":     str(c.get("pov", "Party")),
                    }
                    for i, c in enumerate(parsed)
                ]
                logger.info(f"[OUTLINE] Generated {len(outline)} chapters")
                return outline
        except Exception as e:
            logger.warning(f"[OUTLINE] JSON parse failed: {e} — using fallback")

    # Minimal fallback outline
    logger.warning("[OUTLINE] Using fallback 20-chapter outline")
    return _fallback_outline(title, faction, mission_body)


def _fallback_outline(title: str, faction: str, body: str) -> list[dict]:
    """Generate a minimal structural outline if the AI call fails."""
    acts = [
        # Act 1 — Setup (6 chapters)
        ("Into the Undercity",      "The party arrives and receives the mission briefing. Something feels wrong from the first moment.", "Party"),
        ("The Board",               "The mission posting. The party meets their contact and learns the surface story.", "Contact NPC"),
        ("First Steps",             "Initial investigation. The city reveals itself — district by district, faction by faction.", "Party"),
        ("Wrong Leads",             "A promising lead turns into a dead end. Someone is watching them.", "Party"),
        ("The First Blood",         "The first real confrontation. Not the climax — a warning shot.", "Antagonist"),
        ("What They Don't Tell You","A secret about the mission surfaces. Nothing is what it seemed.", "Party"),
        # Act 2 — Rising Action (11 chapters)
        ("Deeper In",               "The party commits. The city closes around them.", "Party"),
        ("Allies and Enemies",      "New allies with their own agendas. New enemies who know too much.", "Side NPC"),
        ("The Faction Angle",       f"A {faction} operative appears. Whose side are they on?", "Faction NPC"),
        ("Night Run",               "A mission at night. The city is different after dark.", "Party"),
        ("The Wrong Call",          "The party makes a choice they'll regret. Not catastrophically — but it costs them.", "Party"),
        ("Aftermath",               "The consequences of that choice ripple outward. An NPC pays the price.", "Side NPC"),
        ("Going Deeper",            "The real enemy comes into focus. They're not what the party expected.", "Antagonist"),
        ("The Turn",                "The moment the mission changes completely. The surface job was never the real job.", "Party"),
        ("Burning Bridges",         "The party loses something they can't get back. A contact, a resource, a belief.", "Party"),
        ("The Final Shape",         "Everything is now in motion. The endgame is visible.", "Antagonist"),
        ("No More Delays",          "The party prepares for the final confrontation. Old wounds resurface.", "Party"),
        # Act 3 — Climax + Resolution (4 chapters)
        ("The Reckoning",           "The confrontation. Everything that was planted gets paid off here.", "Party"),
        ("Cost",                    "What winning costs. What losing costs. Sometimes both.", "Party"),
        ("After",                   "The Undercity changes. The party changes. One last echo of the mission.", "Party"),
    ]
    return [
        {"num": i + 1, "title": t, "summary": s, "pov": pov}
        for i, (t, s, pov) in enumerate(acts)
    ]
