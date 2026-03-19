"""
rules_agent.py — D&D 5e 2024 (5.5e) rules agent for Tower of Last Chance.

Uses RAG over the local PHB text file to give precise, cited rules answers
grounded in actual book text. Avoids hallucinating mechanics.

Exported:
    answer_rules_question(query: str) -> RulesAnswer
    COMMON_RULES_TOPICS  — dict of category → keywords, for autocomplete hints
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from src.log import logger

# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class RulesAnswer:
    question:    str
    answer:      str
    source_hits: List[str] = field(default_factory=list)
    confidence:  str = "high"   # high / medium / low / not_found
    caveat:      str = ""        # Undercity-specific twist on the rule, if any


# ---------------------------------------------------------------------------
# Undercity rule overrides / additions
# These are canon deviations from RAW that apply to this campaign.
# The agent checks these FIRST and appends them to any PHB answer.
# ---------------------------------------------------------------------------

UNDERCITY_RULE_OVERRIDES = {
    "death saving throw": (
        "⚠️ **Undercity Rule:** The Culinary Council takes notice of repeated death saves. "
        "If a character fails 3 death saves over their career (not just one fight), "
        "they gain 1 point of **Divine Attention** from the Council. This is tracked by the DM."
    ),
    "death": (
        "⚠️ **Undercity Rule:** Death is not necessarily the end — but being claimed by the "
        "Culinary Council is. Characters who die with high LP may be 'harvested' rather than "
        "simply dying. The DM decides based on current Divine Attention levels."
    ),
    "long rest": (
        "⚠️ **Undercity Rule:** Long rests in the Warrens without a secure location require "
        "a DC 12 Perception check or the party is disturbed during rest and only gains "
        "the benefits of a Short Rest instead."
    ),
    "short rest": (
        "⚠️ **Undercity Rule:** Short rests in the Undercity last 1 hour as normal. "
        "However, resting in a Rift-affected area (within 300ft of an active Rift) "
        "requires a DC 14 CON save or the character gains no HP from hit dice spent."
    ),
    "inspiration": (
        "⚠️ **Undercity Rule:** Inspiration is awarded for memorable roleplay, "
        "clever solutions, or actions that align with your character's background. "
        "The DM may also award it for EC spent on bribes that actually work."
    ),
    "attunement": (
        "⚠️ **Undercity Rule:** Rift-touched items may require attunement in an "
        "active Rift seam rather than a Short Rest. The DM will specify per item."
    ),
    "kharma": (
        "📜 **Undercity Currency:** Kharma is crystallised faith, not a D&D RAW mechanic. "
        "It is earned through deeds, sold at Exchange kiosks, and used to fuel Serpent Choir "
        "miracles. Current rate: see `/finances`."
    ),
    "essence coin": (
        "📜 **Undercity Currency:** Essence Coins (EC) are the Undercity's everyday currency. "
        "1 GP ≈ 1 EC as a baseline. Current EC/Kharma rate: see `/finances`."
    ),
    "legend point": (
        "📜 **Undercity Mechanic:** Legend Points (LP) measure narrative significance. "
        "High LP attracts divine attention — including from the Culinary Council. "
        "LP gains are tracked by the DM per the sourcebook tiers."
    ),
    "divine attention": (
        "📜 **Undercity Mechanic:** Divine Attention accumulates as you gain LP and Kharma. "
        "It is not a RAW D&D mechanic — it's a campaign-specific tracker. "
        "High DA means gods are actively watching or intervening in your story."
    ),
    "rift": (
        "📜 **Undercity Mechanic:** Rifts are tears in reality. Entering an active Rift "
        "requires a DC 15 CON save or take 2d6 force damage and gain one level of Exhaustion. "
        "Rift-touched creatures may have resistance to force damage and deal extra force damage."
    ),
    "exhaustion": (
        "⚠️ **5e 2024 Update:** In the 2024 PHB, Exhaustion now works on a 1–10 scale "
        "rather than the old 1–6. Each level imposes a -1 to all D20 Tests (not just ability checks). "
        "At level 10, the character dies."
    ),
}

# Keyword → category mapping for /rules autocomplete suggestions
COMMON_RULES_TOPICS = {
    "Combat": [
        "attack roll", "bonus action", "reaction", "opportunity attack",
        "grapple", "shove", "two-weapon fighting", "flanking", "cover",
        "critical hit", "death saving throw",
    ],
    "Actions": [
        "action", "bonus action", "free action", "dash", "disengage",
        "dodge", "help", "hide", "ready", "search", "use object",
    ],
    "Spellcasting": [
        "concentration", "spell slot", "cantrip", "ritual", "counterspell",
        "spell attack", "saving throw spell", "area of effect", "upcast",
    ],
    "Conditions": [
        "blinded", "charmed", "deafened", "exhaustion", "frightened",
        "grappled", "incapacitated", "invisible", "paralyzed", "petrified",
        "poisoned", "prone", "restrained", "stunned", "unconscious",
    ],
    "Resting": [
        "short rest", "long rest", "hit dice", "recovery",
    ],
    "Ability Checks": [
        "advantage", "disadvantage", "passive perception", "skill check",
        "ability check", "proficiency bonus", "expertise",
    ],
    "Equipment": [
        "attunement", "encumbrance", "ammunition", "improvised weapon",
        "silvered weapon", "magic weapon", "finesse", "versatile",
    ],
    "Undercity Mechanics": [
        "kharma", "essence coin", "legend point", "divine attention", "rift",
    ],
}


# ---------------------------------------------------------------------------
# Core agent function
# ---------------------------------------------------------------------------

async def answer_rules_question(query: str) -> RulesAnswer:
    """
    Answer a D&D 5e 2024 rules question.

    Flow:
    1. Check Undercity overrides (campaign-specific rules take precedence)
    2. RAG search over PHB text chunks
    3. Ask Ollama to synthesise an answer from the retrieved chunks
    4. Return RulesAnswer with the answer + any override caveats
    """
    from src.tower_rag import search_docs

    query_lower = query.lower()

    # Step 1: check for Undercity-specific rules/terms
    override_text = ""
    for keyword, override in UNDERCITY_RULE_OVERRIDES.items():
        if keyword in query_lower:
            override_text = override
            break

    # Step 2: RAG retrieval — always include rules docs
    try:
        hits = search_docs(query, top_k=6)
        context_block = "\n\n---\n\n".join(hits) if hits else ""
    except Exception as e:
        logger.warning(f"rules_agent RAG error: {e}")
        hits = []
        context_block = ""

    # Step 3: Build Ollama prompt
    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    if context_block:
        rag_block = f"RELEVANT RULEBOOK EXCERPTS:\n{context_block}"
        confidence_hint = "high"
    else:
        rag_block = "No matching excerpts found. Answer from general D&D 5e 2024 knowledge."
        confidence_hint = "medium"

    prompt = f"""You are a precise D&D 5e 2024 (also called 5.5e) rules expert.
You answer rules questions clearly and accurately using the provided rulebook text.

{rag_block}

QUESTION: {query}

RULES FOR YOUR ANSWER:
- Answer based on the excerpts above if they cover the topic. Quote the key rule briefly.
- If the excerpts don't fully answer it, use your D&D 5e 2024 knowledge but say so.
- Be concise: 2–6 lines. Use Discord markdown (**bold** for key terms, `inline code` for dice/numbers).
- State the rule clearly first. Then explain any edge cases or clarifications.
- Do NOT write "According to the Player's Handbook..." — just state the rule.
- Do NOT repeat the question back.
- Do NOT add preamble or sign-off.
- Output ONLY the answer."""

    try:
        import httpx
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ollama_url, json={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            })
            resp.raise_for_status()
            data = resp.json()

        answer = ""
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                answer = msg.get("content", "").strip()

        # Strip AI preamble
        lines = answer.splitlines()
        skip  = ("sure", "here's", "here is", "certainly", "of course", "below is", "great question")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        answer = "\n".join(lines).strip()

        if not answer:
            return RulesAnswer(
                question=query,
                answer="*No answer found in the rulebook or general knowledge.*",
                source_hits=hits,
                confidence="not_found",
                caveat=override_text,
            )

        return RulesAnswer(
            question=query,
            answer=answer,
            source_hits=hits,
            confidence=confidence_hint,
            caveat=override_text,
        )

    except Exception as e:
        import traceback
        logger.error(f"rules_agent Ollama error: {type(e).__name__}: {e}\n{traceback.format_exc()}")
        return RulesAnswer(
            question=query,
            answer=f"*Rules lookup failed: {type(e).__name__}*",
            source_hits=[],
            confidence="not_found",
            caveat=override_text,
        )


# ---------------------------------------------------------------------------
# Spell / feature lookup helper (structured quick-reference)
# ---------------------------------------------------------------------------

_SPELL_LOOKUP_PROMPT = """You are a D&D 5e 2024 spell and class feature reference.

RELEVANT RULEBOOK EXCERPTS:
{context}

Look up: {query}

Provide a structured reference block using this EXACT format (fill in all fields, use 'N/A' if not applicable):

**{name}**
📗 *{type} — {school_or_category}*
⏱ **Cast/Activate:** {casting_time}
📏 **Range:** {range}
⏳ **Duration:** {duration}  {concentration}
🎯 **Target/Area:** {target}
💥 **Effect:** {effect_summary}
📈 **Higher Levels/Scaling:** {upcast_or_scaling}

Keep Effect to 2-3 lines max. Output ONLY this block. No preamble."""


async def lookup_spell_or_feature(name: str) -> str:
    """
    Returns a structured Discord-formatted reference block for a spell or class feature.
    """
    from src.tower_rag import search_docs
    import httpx

    ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
    ollama_url   = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")

    try:
        hits = search_docs(name, top_k=4)
        context = "\n\n---\n\n".join(hits) if hits else "(Not found in loaded rulebook excerpts.)"
    except Exception:
        context = "(RAG unavailable.)"

    prompt = _SPELL_LOOKUP_PROMPT.format(
        context=context,
        query=name,
        name=name,
        type="{type}",
        school_or_category="{school_or_category}",
        casting_time="{casting_time}",
        range="{range}",
        duration="{duration}",
        concentration="{concentration}",
        target="{target}",
        effect_summary="{effect_summary}",
        upcast_or_scaling="{upcast_or_scaling}",
    )

    # Re-format without placeholder braces confusing the model
    prompt = _SPELL_LOOKUP_PROMPT.replace("{context}", context).replace("{query}", name)
    # Replace remaining literal template vars with their field names
    for tag in ["name", "type", "school_or_category", "casting_time", "range",
                "duration", "concentration", "target", "effect_summary", "upcast_or_scaling"]:
        prompt = prompt.replace("{" + tag + "}", f"[{tag}]")
    prompt = prompt.replace("[name]", name)

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
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
        skip  = ("sure", "here's", "here is", "certainly", "of course", "below is")
        while lines and lines[0].lower().strip().rstrip("!:,.").startswith(skip):
            lines.pop(0)
        return "\n".join(lines).strip() or "*Not found.*"

    except Exception as e:
        logger.error(f"lookup_spell_or_feature error: {e}")
        return f"*Lookup failed: {type(e).__name__}*"
