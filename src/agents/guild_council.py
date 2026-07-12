"""Guild Council — Governing body for world-state decisions.

The Grand Council of Guilds convenes during each learning cycle to deliberate
on proposed rulings that affect the Undercity's ongoing campaign world.

Structure:
  - 6 Council Members, each representing a major faction
  - 1 elected President (Guildmaster of the Adventurers Guild) — tiebreaker only
  - Simple majority wins; President votes only on 3-3 ties

Process per session:
  1. World briefing assembled from DB state + specialist agent findings
  2. Secretariat proposes 2-3 rulings based on current events
  3. All 6 members debate and vote in parallel
  4. Results tallied — passed rulings applied and posted as bulletin
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.log import logger


# ── Council Composition ────────────────────────────────────────────────────

COUNCIL_MEMBERS = [
    {
        "name":       "Director Myra Kess",
        "faction":    "Tower Authority / FTA",
        "title":      "Chief Compliance Director",
        "agenda":     "Tower revenue, FTA licensing, order, regulation compliance",
        "bias":       "Votes YES on anything that expands Tower oversight or fees. Votes NO on anything that weakens FTA authority.",
        "voice":      "Bureaucratic, precise, quotes section numbers. Cold.",
    },
    {
        "name":       "Lady Cerys Valemont",
        "faction":    "Argent Blades",
        "title":      "Guildmaster, Argent Blades",
        "agenda":     "Arena prestige, combat quality, Argent Blades contracts and influence",
        "bias":       "Votes YES on anything that elevates combat tiers or Blade visibility. Votes NO on restrictions that hamper the Arena.",
        "voice":      "Decisive, short sentences. Everything is a test of strength. Slightly contemptuous of weakness.",
    },
    {
        "name":       "Senior Archivist Pell",
        "faction":    "Glass Sigil",
        "title":      "Senior Archivist, Glass Sigil",
        "agenda":     "Knowledge access, arcane licensing, Sigil archive authority, information control",
        "bias":       "Votes YES on anything that requires documentation or expands Sigil authority. Votes NO on hasty decisions without precedent.",
        "voice":      "Academic, measured. References historical precedent. Long pauses implied.",
    },
    {
        "name":       "High Apostle Yzura",
        "faction":    "Serpent Choir",
        "title":      "High Apostle, Serpent Choir",
        "agenda":     "Divine contract integrity, resurrection market, Choir influence, soul-harvest alignment",
        "bias":       "Votes YES on anything that maintains cosmic order or benefits the Choir's divine contracts. Votes NO on anything that cheapens life or death.",
        "voice":      "Eerily calm. Speaks about fate as if already decided. Smiles while saying terrible things.",
    },
    {
        "name":       "Serrik Dhal",
        "faction":    "Iron Fang Consortium",
        "title":      "Director-General, Iron Fang Consortium",
        "agenda":     "Consortium profit, supply chain dominance, EC flow, trade routes",
        "bias":       "Votes YES on anything that moves EC or expands trade. Votes NO on anything that hurts Consortium margins or restricts commerce.",
        "voice":      "Merchant-smooth. Everything has a price. Affable and dangerous.",
    },
    {
        "name":       "Pol Greaves",
        "faction":    "Patchwork Saints",
        "title":      "High Representative, Patchwork Saints",
        "agenda":     "Warrens welfare, humanitarian access, anti-exploitation, healer protections",
        "bias":       "Votes YES on anything that protects the poor or limits faction profiteering. Votes NO on policies that harm residents.",
        "voice":      "Passionate, blunt, will grandstand. Speaks for people not in the room.",
    },
]

COUNCIL_PRESIDENT = {
    "name":    "Guildmaster Mari Fen",
    "faction": "Adventurers Guild (elected President)",
    "title":   "Guildmaster & President of the Grand Council",
    "agenda":  "Balance, stability, adventurer welfare, council legitimacy",
    "bias":    "Tiebreaker only. Votes for long-term stability over any single faction's gain.",
    "voice":   "Pragmatic, fair, slightly exhausted. Has seen too many councils collapse.",
}


# ── Data Classes ───────────────────────────────────────────────────────────

@dataclass
class CouncilRuling:
    """A single ruling proposal and its voting outcome."""
    index:         int
    proposal:      str          # The ruling text (1-2 sentences)
    topic:         str          # Short topic label
    votes_yes:     list[str]    = field(default_factory=list)
    votes_no:      list[str]    = field(default_factory=list)
    positions:     dict[str, str] = field(default_factory=dict)   # name → statement
    tiebreak_used: bool         = False
    tiebreak_vote: str          = ""   # "YES" or "NO"
    passed:        bool         = False


@dataclass
class CouncilSession:
    """Full council session result."""
    session_date:  str
    rulings:       list[CouncilRuling]
    bulletin_text: str
    passed_count:  int
    failed_count:  int
    world_changes: list[str]   = field(default_factory=list)


# ── Ollama helper ──────────────────────────────────────────────────────────

async def _ollama_call(prompt: str, num_predict: int = 300) -> Optional[str]:
    """Single Ollama call via the queue. Returns text or None."""
    ollama_model = os.getenv("OLLAMA_FAST_MODEL", os.getenv("OLLAMA_MODEL", "qwen3-8b-slim:latest"))

    # think: True needs a much larger budget — thinking tokens count against num_predict.
    # Minimum viable: 512 tokens for a member vote (thinking ~300 + response ~100).
    # We always pass at least 1024 regardless of what the caller requested.
    effective_predict = max(num_predict, 1024)

    # Fit the context window to the prompt + reply instead of a fixed 8192 —
    # an oversized prompt is silently truncated by Ollama (empty/1-char reply).
    _needed = len(prompt) // 4 + effective_predict + 768
    _num_ctx = next((c for c in (8192, 12288, 16384, 24576, 32768) if c >= _needed), 32768)

    try:
        from src.ollama_queue import call_ollama
        data = await call_ollama(
            payload={
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "num_predict": effective_predict,
                    "think": True,
                    "num_ctx": _num_ctx,
                },
            },
            timeout=240.0,
            caller="guild_council",
            force=True,
        )
        if isinstance(data, dict):
            msg = data.get("message", {})
            if isinstance(msg, dict):
                content = msg.get("content", "").strip()
                # Strip qwen3 think blocks — content field sometimes includes them
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                logger.info(
                    f"🏛️ Ollama response ({effective_predict} predict): "
                    f"{len(content)} chars | preview: {content[:80].replace(chr(10),' ')!r}"
                )
                return content or None
    except Exception as e:
        logger.warning(f"🏛️ Council Ollama error: {e!r}")
    return None


# ── Council class ──────────────────────────────────────────────────────────

class GuildCouncil:
    """
    The Grand Council of Guilds.

    Call `run_session(world_briefing, channel)` to run a full deliberation.
    """

    # council_rulings stored in global_state DB key (no file I/O)
    _RULINGS_STATE_KEY = "council_rulings"
    _DEFAULT_SESSION_TIMEOUT_SECONDS = 45 * 60

    # ── World briefing builder ─────────────────────────────────────────────

    @staticmethod
    def build_briefing(
        specialist_findings: list[str] | None = None,
        world_data: dict | None = None,
    ) -> str:
        """Build the world-state briefing text given to the Secretariat and members."""
        lines = ["GRAND COUNCIL — WORLD BRIEFING"]
        today = datetime.now().strftime("%Y-%m-%d")
        lines.append(f"Date: {today}")
        lines.append("")

        # Pull live world state
        try:
            from src.db_api import raw_query, get_rift_state
            # Recent news
            news = raw_query(
                "SELECT facts FROM news_memory ORDER BY created_at DESC LIMIT 5"
            ) or []
            if news:
                lines.append("RECENT EVENTS:")
                for n in news:
                    fact = n.get("facts", "")
                    if fact:
                        lines.append(f"  - {str(fact)[:120]}")
                lines.append("")

            # Active missions
            missions = raw_query(
                "SELECT COUNT(*) as cnt, tier FROM missions "
                "WHERE status = 'active' GROUP BY tier"
            ) or []
            if missions:
                lines.append("MISSION BOARD:")
                for m in missions:
                    lines.append(f"  - {m['cnt']} active {m['tier']} tier missions")
                lines.append("")

            # Faction standing
            factions = raw_query(
                "SELECT faction_name, tier, reputation_score "
                "FROM faction_reputation ORDER BY reputation_score DESC LIMIT 8"
            ) or []
            if factions:
                lines.append("FACTION STANDINGS:")
                for f in factions:
                    lines.append(
                        f"  - {f['faction_name']}: {f['tier']} "
                        f"({f['reputation_score']:+d} rep)"
                    )
                lines.append("")

            # Rift state
            rift = get_rift_state() or {}
            active_rifts = [r for r in rift.get("rifts", []) if not r.get("resolved")]
            if active_rifts:
                lines.append(f"RIFT ALERTS: {len(active_rifts)} active rift(s)")
                for r in active_rifts[:3]:
                    lines.append(f"  - {r.get('location','unknown')}: stage {r.get('stage','?')}")
                lines.append("")

            # Graveyard count
            dead = raw_query(
                "SELECT COUNT(*) as cnt FROM npcs WHERE status = 'dead'"
            ) or [{"cnt": 0}]
            lines.append(f"GRAVEYARD: {dead[0]['cnt']} confirmed deaths on record")
            lines.append("")

            # Council outcome dispatches from last 14 days — shows members how past rulings played out
            outcomes = raw_query(
                "SELECT facts, created_at FROM news_memory "
                "WHERE news_type = 'council_outcome' "
                "AND created_at >= DATE_SUB(NOW(), INTERVAL 14 DAY) "
                "ORDER BY created_at DESC LIMIT 6"
            ) or []
            if outcomes:
                lines.append("RECENT RULING OUTCOMES (how last session's decisions played out):")
                for o in outcomes:
                    lines.append(f"  - {str(o.get('facts',''))[:180]}")
                lines.append("")

        except Exception as e:
            logger.warning(f"🏛️ Council briefing DB error: {e}")

        # Specialist findings
        if specialist_findings:
            lines.append("SPECIALIST AGENT FINDINGS:")
            for finding in specialist_findings[:5]:
                lines.append(f"  - {finding[:150]}")
            lines.append("")

        return "\n".join(lines)

    # ── Ruling proposal ────────────────────────────────────────────────────

    async def _propose_rulings(self, briefing: str) -> list[dict]:
        """
        Ask the Secretariat to draft 2 concrete ruling proposals
        based on the current world state, avoiding already-decided topics.
        """
        # Build exclusion list from DB
        decided = self._load_decided_topics()
        exclusion_block = ""
        if decided:
            # Show last 20 decided topics (enough to avoid repeats without overwhelming)
            recent = decided[-20:]
            exclusion_block = "\nALREADY DECIDED — do NOT bring these back:\n"
            for d in recent:
                outcome = "PASSED" if d.get("passed") else "REJECTED"
                exclusion_block += f'  [{outcome}] {d["topic"]}: "{d["proposal"][:100]}"\n'
            exclusion_block += "\nPropose entirely NEW issues not on this list.\n"

        prompt = f"""{briefing}
{exclusion_block}
You are the Grand Council Secretariat. Based on the above world briefing,
draft exactly 2 short ruling proposals for the Council to vote on today.

Each ruling must:
- Be a specific, enforceable decision (not vague)
- Respond directly to something in the briefing (recent events, faction tension, rift activity, deaths)
- Have a realistic faction impact
- NOT repeat or revisit any already-decided topic above

Output ONLY a JSON array with 2 objects, like:
[
  {{"topic": "Short topic label", "proposal": "The full ruling text — 1-2 sentences."}},
  {{"topic": "Short topic label", "proposal": "The full ruling text — 1-2 sentences."}}
]

Do NOT include any other text, preamble, or markdown fences."""

        text = await _ollama_call(prompt, num_predict=2048)
        if not text:
            logger.warning("🏛️ Secretariat got no response — using fallback rulings")
            return self._fallback_rulings(decided)

        # Strip fences and parse
        text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        try:
            rulings = json.loads(text)
            if isinstance(rulings, list):
                return [r for r in rulings if r.get("proposal")][:3]
        except Exception:
            # Try to find a JSON array in the response
            m = re.search(r"\[.*\]", text, re.DOTALL)
            if m:
                try:
                    rulings = json.loads(m.group())
                    return [r for r in rulings if r.get("proposal")][:3]
                except Exception:
                    pass
        logger.warning("🏛️ Could not parse ruling proposals — using fallbacks")
        return self._fallback_rulings(decided)

    def _fallback_rulings(self, decided: list[dict] | None = None) -> list[dict]:
        """
        Fallback rulings if the Secretariat LLM fails.
        Rotates through a pool of 12 topics, skipping any already decided.
        """
        import random

        decided_topics = {d.get("topic", "").lower() for d in (decided or [])}

        pool = [
            {
                "topic": "Mission Reward Review",
                "proposal": "The Council directs a 10% review of Tier 3 mission rewards to reflect current rift danger levels.",
            },
            {
                "topic": "Graveyard Access",
                "proposal": "All faction-affiliated deaths must be reported to the Patchwork Saints within 24 hours.",
            },
            {
                "topic": "Rift Hazard Pay",
                "proposal": "Adventurers clearing active rift zones receive a 15% hazard bonus on top of posted reward.",
            },
            {
                "topic": "Bounty Transparency",
                "proposal": "All active bounties above 500 EC must be publicly registered with the Glass Sigil archive.",
            },
            {
                "topic": "NPC Witness Protections",
                "proposal": "Witnesses to faction crimes may request anonymity through the Patchwork Saints without FTA documentation.",
            },
            {
                "topic": "Arena Scheduling Conflict",
                "proposal": "Mission board postings may not expire during Arena championship weeks to prevent competition for adventurer availability.",
            },
            {
                "topic": "Tier Cap Review",
                "proposal": "The Council reviews whether the current Tier 4 mission cap is appropriate given recent party performance metrics.",
            },
            {
                "topic": "FTA Inspection Rights",
                "proposal": "The FTA's right to inspect Guild-registered safe houses is suspended pending review of overreach complaints.",
            },
            {
                "topic": "Serpent Choir Contract Audit",
                "proposal": "All resurrection contracts signed this quarter are audited for compliance with the standard soul-return clause.",
            },
            {
                "topic": "Iron Fang Trade Route",
                "proposal": "The Consortium's monopoly on the eastern supply corridor is reviewed after three reported supply interruptions.",
            },
            {
                "topic": "Warrens Curfew Proposal",
                "proposal": "A proposed curfew in the Deep Warrens after the third hour is tabled for Council vote.",
            },
            {
                "topic": "Glass Sigil Archive Fee",
                "proposal": "Access fees for the Glass Sigil public archive are reduced by 50% for registered adventurers.",
            },
        ]

        # Filter out already-decided topics
        available = [r for r in pool if r["topic"].lower() not in decided_topics]
        if len(available) < 2:
            # All known topics exhausted — reset and reuse
            available = pool[:]

        random.shuffle(available)
        selected = available[:2]
        logger.info(f"🏛️ Fallback rulings selected: {[r['topic'] for r in selected]}")
        return selected

    # ── Member voting ──────────────────────────────────────────────────────

    async def _member_vote(
        self,
        member: dict,
        ruling: dict,
        briefing: str,
        prior_statements: list[tuple[str, str]] | None = None,
    ) -> tuple[str, str]:
        """
        Ask a single council member to state their position and vote.
        prior_statements: list of (member_name, statement) from earlier speakers.
        Returns (vote: "YES"|"NO", position_statement: str).
        """
        debate_context = ""
        if prior_statements:
            debate_context = "\nCOUNCIL DEBATE SO FAR:\n"
            for speaker, stmt in prior_statements:
                debate_context += f'  {speaker}: "{stmt}"\n'
            debate_context += "\nYou've heard what your colleagues said. Respond to their arguments if relevant.\n"

        if prior_statements:
            speak_note = "React to the debate above and state your final position."
        else:
            speak_note = "You speak first. Set the tone for the debate."

        prompt = f"""You are {member['name']}, {member['title']} of the {member['faction']}.
Your agenda: {member['agenda']}
Your bias: {member['bias']}
Your voice: {member['voice']}

WORLD CONTEXT:
{briefing[:500]}

PROPOSED RULING:
"{ruling['proposal']}"
{debate_context}
{speak_note}

Do not merely vote your faction bias. In 2-3 sentences:
- Name the strongest argument FOR the ruling
- Name the strongest objection or cost
- Explain why your faction accepts or rejects that tradeoff

Format exactly:
POSITION: [your statement]
VOTE: YES  or  VOTE: NO"""

        text = await _ollama_call(prompt, num_predict=1024)
        if not text:
            logger.warning(f"🏛️ {member['name']} got no response — recording abstain")
            return "ABSTAIN", f"[{member['name']} did not respond — Ollama returned empty]"

        vote = "ABSTAIN"
        statement = text.strip()

        vote_match = re.search(r"VOTE:\s*(YES|NO)", text, re.IGNORECASE)
        if vote_match:
            vote = vote_match.group(1).upper()

        pos_match = re.search(r"POSITION:\s*(.+?)(?:\n|VOTE:|$)", text, re.IGNORECASE | re.DOTALL)
        if pos_match:
            statement = pos_match.group(1).strip()
        elif vote_match:
            statement = text[:vote_match.start()].strip()

        statement = re.sub(r"^POSITION:\s*", "", statement, flags=re.IGNORECASE).strip()
        if not statement:
            statement = "[No statement recorded]"

        return vote, statement

    async def _member_debate_statement(
        self,
        member: dict,
        ruling: dict,
        briefing: str,
        prior_statements: list[tuple[str, str]] | None = None,
    ) -> str:
        """Ask a member to argue before any final proposal or vote exists."""
        debate_context = ""
        if prior_statements:
            debate_context = "\nCOUNCIL ARGUMENTS SO FAR:\n"
            for speaker, stmt in prior_statements:
                debate_context += f'  {speaker}: "{stmt}"\n'

        prompt = f"""You are {member['name']}, {member['title']} of the {member['faction']}.
Your agenda: {member['agenda']}
Your bias: {member['bias']}
Your voice: {member['voice']}

WORLD CONTEXT:
{briefing[:700]}

DRAFT ISSUE BEFORE THE COUNCIL:
Topic: {ruling.get('topic', 'Council issue')}
Draft proposal: "{ruling['proposal']}"
{debate_context}
This is debate, not a vote. Argue the issue in character.

Requirements:
- Directly answer or challenge at least one prior argument if any exists
- State one condition, amendment, or concession that would make this ruling acceptable or unacceptable
- Give a concrete reason grounded in your faction's interests, not a generic slogan
- 2-3 sentences only

Output only your spoken argument."""

        text = await _ollama_call(prompt, num_predict=1024)
        if not text:
            return f"[{member['name']} was silent; no argument recorded]"
        return re.sub(r"^POSITION:\s*", "", text.strip(), flags=re.IGNORECASE).strip()

    async def _revise_ruling_after_debate(
        self,
        ruling: dict,
        briefing: str,
        debate: list[tuple[str, str]],
    ) -> dict:
        """Turn council arguments into the final ruling members vote on."""
        debate_block = "\n".join(f"- {speaker}: {stmt}" for speaker, stmt in debate)
        prompt = f"""{briefing[:900]}

The Grand Council debated this draft proposal:
Topic: {ruling.get('topic', 'Council issue')}
Draft: "{ruling['proposal']}"

ARGUMENTS:
{debate_block[:3500]}

You are the Council Secretariat. Draft the FINAL ruling for vote.

The final ruling must:
- Be one enforceable decision, 1-2 sentences
- Preserve the issue's intent
- Include at least one concession, safeguard, enforcement detail, or review clause that responds to the debate
- Avoid vague language like "consider", "encourage", or "review" unless a deadline/owner is named

Output ONLY JSON:
{{"topic": "short topic", "proposal": "final ruling text"}}"""

        text = await _ollama_call(prompt, num_predict=1536)
        if text:
            cleaned = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
            try:
                obj = json.loads(cleaned)
                if isinstance(obj, dict) and obj.get("proposal"):
                    return {
                        "topic": obj.get("topic") or ruling.get("topic", "Council issue"),
                        "proposal": obj["proposal"],
                    }
            except Exception:
                m = re.search(r"\{.*\}", cleaned, re.DOTALL)
                if m:
                    try:
                        obj = json.loads(m.group())
                        if isinstance(obj, dict) and obj.get("proposal"):
                            return {
                                "topic": obj.get("topic") or ruling.get("topic", "Council issue"),
                                "proposal": obj["proposal"],
                            }
                    except Exception:
                        pass

        logger.warning("🏛️ Secretariat could not revise ruling — voting on original draft")
        return ruling

    async def _president_vote(
        self, ruling: dict, briefing: str,
        prior_statements: list[tuple[str, str]] | None = None,
    ) -> tuple[str, str]:
        """Ask the President for a tiebreaker vote, with full debate context."""
        p = COUNCIL_PRESIDENT
        debate_block = ""
        if prior_statements:
            debate_block = "\nTHE COUNCIL DEBATE:\n"
            for speaker, stmt in prior_statements:
                debate_block += f'  {speaker}: "{stmt}"\n'

        prompt = f"""You are {p['name']}, {p['title']}.
The vote on this ruling is TIED 3-3. As President, you must cast the deciding vote.
Your agenda: {p['agenda']}
Your voice: {p['voice']}

PROPOSED RULING:
"{ruling['proposal']}"
{debate_block}
You have heard all arguments. Your word is final. Decide.
Format:
POSITION: [your reasoning — may acknowledge the debate]
VOTE: YES  (or VOTE: NO)"""

        text = await _ollama_call(prompt, num_predict=1024)
        if not text:
            logger.warning("🏛️ President got no response — motion fails by default")
            return "NO", "[President declined to vote — motion fails by default]"

        vote = "NO"
        statement = "[No statement]"
        vote_match = re.search(r"VOTE:\s*(YES|NO)", text, re.IGNORECASE)
        if vote_match:
            vote = vote_match.group(1).upper()
        pos_match = re.search(r"POSITION:\s*(.+?)(?:\n|VOTE:|$)", text, re.IGNORECASE | re.DOTALL)
        if pos_match:
            statement = pos_match.group(1).strip()
        return vote, statement

    # ── Full ruling deliberation ───────────────────────────────────────────

    async def _deliberate_ruling(
        self,
        index: int,
        ruling_proposal: dict,
        briefing: str,
    ) -> CouncilRuling:
        """Run members sequentially so each one sees the prior debate, then tally."""
        ruling = CouncilRuling(
            index=index,
            proposal=ruling_proposal["proposal"],
            topic=ruling_proposal.get("topic", f"Ruling {index}"),
        )

        prior_statements: list[tuple[str, str]] = []

        # Sequential debate — each member sees what came before
        for member in COUNCIL_MEMBERS:
            logger.info(f"🏛️   → asking {member['name']} ({member['faction']}) ...")
            try:
                vote, statement = await self._member_vote(
                    member, ruling_proposal, briefing, prior_statements
                )
            except Exception as e:
                logger.warning(f"🏛️   {member['name']} EXCEPTION: {e!r}")
                ruling.positions[member["name"]] = f"[Error: {e}]"
                continue

            ruling.positions[member["name"]] = statement
            prior_statements.append((member["name"], statement))

            if vote == "YES":
                ruling.votes_yes.append(member["name"])
            elif vote == "NO":
                ruling.votes_no.append(member["name"])
            # ABSTAIN: counted neither way

            logger.info(
                f"🏛️   {member['name']}: {vote} | "
                f"{statement[:80].replace(chr(10), ' ')!r}"
            )

        yes = len(ruling.votes_yes)
        no  = len(ruling.votes_no)

        if yes > no:
            ruling.passed = True
        elif no > yes:
            ruling.passed = False
        else:
            # Tie — President casts deciding vote with full debate context
            ruling.tiebreak_used = True
            pv, ps = await self._president_vote(ruling_proposal, briefing, prior_statements)
            ruling.tiebreak_vote = pv
            ruling.positions[COUNCIL_PRESIDENT["name"]] = ps
            ruling.passed = (pv == "YES")

        result_str = "PASSED" if ruling.passed else "FAILED"
        logger.info(
            f"🏛️ Ruling {index} ({ruling.topic}): {result_str} "
            f"[{yes}-{no}{'+ tiebreak' if ruling.tiebreak_used else ''}]"
        )
        return ruling

    async def _deliberate_ruling_v2(
        self,
        index: int,
        ruling_proposal: dict,
        briefing: str,
    ) -> CouncilRuling:
        """Run debate, synthesize a final ruling, then run a reasoned vote."""
        debate_statements: list[tuple[str, str]] = []

        logger.info(f"Council ruling {index}: debate round opening")
        for member in COUNCIL_MEMBERS:
            logger.info(f"Council debate: {member['name']} ({member['faction']})")
            try:
                statement = await self._member_debate_statement(
                    member, ruling_proposal, briefing, debate_statements
                )
            except Exception as e:
                logger.warning(f"Council debate error for {member['name']}: {e!r}")
                statement = f"[Error during debate: {e}]"
            debate_statements.append((member["name"], statement))
            logger.info(f"Council argument from {member['name']}: {statement[:100].replace(chr(10), ' ')!r}")

        final_proposal = await self._revise_ruling_after_debate(
            ruling_proposal, briefing, debate_statements
        )
        logger.info(
            f"Council ruling {index}: final proposal for vote: "
            f"{final_proposal.get('proposal', '')[:160].replace(chr(10), ' ')!r}"
        )

        ruling = CouncilRuling(
            index=index,
            proposal=final_proposal["proposal"],
            topic=final_proposal.get("topic", ruling_proposal.get("topic", f"Ruling {index}")),
        )
        prior_statements = debate_statements[:]

        for member in COUNCIL_MEMBERS:
            logger.info(f"Council vote: {member['name']} ({member['faction']})")
            try:
                vote, statement = await self._member_vote(
                    member, final_proposal, briefing, prior_statements
                )
            except Exception as e:
                logger.warning(f"Council vote error for {member['name']}: {e!r}")
                ruling.positions[member["name"]] = f"[Error: {e}]"
                continue

            ruling.positions[member["name"]] = statement
            if vote == "YES":
                ruling.votes_yes.append(member["name"])
            elif vote == "NO":
                ruling.votes_no.append(member["name"])

            logger.info(
                f"Council vote from {member['name']}: {vote} | "
                f"{statement[:80].replace(chr(10), ' ')!r}"
            )

        yes = len(ruling.votes_yes)
        no = len(ruling.votes_no)

        if yes > no:
            ruling.passed = True
        elif no > yes:
            ruling.passed = False
        else:
            ruling.tiebreak_used = True
            pv, ps = await self._president_vote(final_proposal, briefing, prior_statements)
            ruling.tiebreak_vote = pv
            ruling.positions[COUNCIL_PRESIDENT["name"]] = ps
            ruling.passed = (pv == "YES")

        result_str = "PASSED" if ruling.passed else "FAILED"
        logger.info(
            f"Council ruling {index} ({ruling.topic}): {result_str} "
            f"[{yes}-{no}{'+ tiebreak' if ruling.tiebreak_used else ''}]"
        )
        return ruling

    # ── Session runner ─────────────────────────────────────────────────────

    async def run_session(
        self,
        specialist_findings: list[str] | None = None,
        world_data: dict | None = None,
        channel=None,
    ) -> CouncilSession:
        """Run a full council session with an overall timeout guard."""
        timeout = self._session_timeout_seconds()
        try:
            if timeout is None:
                return await self._run_session_impl(specialist_findings, world_data, channel)
            return await asyncio.wait_for(
                self._run_session_impl(specialist_findings, world_data, channel),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            if timeout is None:
                raise
            logger.warning(f"Council session timed out after {timeout:.1f}s; adjourning without rulings")
            session = CouncilSession(
                session_date=datetime.now().strftime("%Y-%m-%d"),
                rulings=[],
                bulletin_text=(
                    f"**GRAND COUNCIL ADJOURNED - {datetime.now().strftime('%Y-%m-%d')}**\n"
                    f"The session exceeded its {timeout:.0f}-second limit before any ruling could be finalized."
                ),
                passed_count=0,
                failed_count=0,
                world_changes=["Council session timed out; no rulings recorded."],
            )
            if channel:
                await self._post_bulletin(session, channel)
            self._write_journal(session)
            return session

    def _session_timeout_seconds(self) -> float | None:
        raw = os.getenv("GUILD_COUNCIL_SESSION_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return float(self._DEFAULT_SESSION_TIMEOUT_SECONDS)
        try:
            timeout = float(raw)
        except ValueError:
            logger.warning(
                f"Invalid GUILD_COUNCIL_SESSION_TIMEOUT_SECONDS={raw!r}; "
                f"using {self._DEFAULT_SESSION_TIMEOUT_SECONDS}s"
            )
            return float(self._DEFAULT_SESSION_TIMEOUT_SECONDS)
        return timeout if timeout > 0 else None

    async def _run_session_impl(
        self,
        specialist_findings: list[str] | None = None,
        world_data: dict | None = None,
        channel=None,
    ) -> CouncilSession:
        """Run a full council session. Posts bulletin to channel if provided."""
        briefing = self.build_briefing(specialist_findings, world_data)
        logger.info("🏛️ Grand Council convening…")

        # Propose rulings
        proposals = await self._propose_rulings(briefing)
        logger.info(f"🏛️ Secretariat proposed {len(proposals)} ruling(s)")

        # Deliberate each ruling sequentially (not parallel — cleaner logs)
        rulings = []
        for i, proposal in enumerate(proposals, 1):
            ruling = await self._deliberate_ruling_v2(i, proposal, briefing)
            rulings.append(ruling)
            await asyncio.sleep(1)  # brief pause between rulings

        # Build session
        passed = [r for r in rulings if r.passed]
        failed = [r for r in rulings if not r.passed]

        session = CouncilSession(
            session_date=datetime.now().strftime("%Y-%m-%d"),
            rulings=rulings,
            bulletin_text="",
            passed_count=len(passed),
            failed_count=len(failed),
        )

        # Format bulletin
        session.bulletin_text = self._format_bulletin(session)

        # Persist all rulings (pass AND fail) so topics aren't repeated
        session.world_changes = await self._apply_passed_rulings(rulings)

        # Post to Discord
        if channel:
            await self._post_bulletin(session, channel)

        # Log to journal
        self._write_journal(session)

        logger.info(
            f"🏛️ Council session complete — {session.passed_count} passed, "
            f"{session.failed_count} failed"
        )
        return session

    # ── Bulletin formatter ─────────────────────────────────────────────────

    def _format_bulletin(self, session: CouncilSession) -> str:
        """Format the session as an in-world Council bulletin."""
        lines = [
            f"**📜 GRAND COUNCIL BULLETIN — {session.session_date}**",
            "*The Grand Council of Guilds has deliberated and ruled as follows.*",
            "",
        ]

        for ruling in session.rulings:
            status_emoji = "✅" if ruling.passed else "❌"
            result_label = "**PASSED**" if ruling.passed else "**FAILED**"
            yes_count = len(ruling.votes_yes)
            no_count  = len(ruling.votes_no)
            vote_str  = f"{yes_count}-{no_count}"
            if ruling.tiebreak_used:
                vote_str += f" (tiebreak: {COUNCIL_PRESIDENT['name']} voted {ruling.tiebreak_vote})"

            lines += [
                f"─────────────────────────────────",
                f"**RULING {ruling.index} — {ruling.topic.upper()}**",
                f"> {ruling.proposal}",
                "",
            ]

            # Member positions
            for member in COUNCIL_MEMBERS:
                mname = member["name"]
                vote_icon = "✅" if mname in ruling.votes_yes else "❌"
                statement = ruling.positions.get(mname, "")
                lines.append(f"{vote_icon} **{mname}** ({member['faction']})")
                if statement and statement != "[No statement recorded]":
                    lines.append(f'  *"{statement}"*')

            # Tiebreak
            if ruling.tiebreak_used:
                pname = COUNCIL_PRESIDENT["name"]
                tie_icon = "✅" if ruling.tiebreak_vote == "YES" else "❌"
                lines.append(f"{tie_icon} **{pname}** *(tiebreaker)*")
                pstatement = ruling.positions.get(pname, "")
                if pstatement:
                    lines.append(f'  *"{pstatement}"*')

            lines += [
                "",
                f"{status_emoji} {result_label} — {vote_str}",
            ]

            # Winning argument summary — quote the strongest statement from the prevailing side
            winning_names = ruling.votes_yes if ruling.passed else ruling.votes_no
            winning_statements = [
                (n, ruling.positions.get(n, ""))
                for n in winning_names
                if ruling.positions.get(n, "") not in ("", "[No statement recorded]", "[Error — no vote recorded]")
            ]
            if winning_statements:
                # Pick the longest / most substantive statement as the key argument
                best_name, best_stmt = max(winning_statements, key=lambda x: len(x[1]))
                side = "prevailing argument" if ruling.passed else "dissenting argument"
                lines.append(f"*Key {side} — {best_name}: \"{best_stmt}\"*")

            lines.append("")

        lines += [
            "─────────────────────────────────",
            f"Session summary: {session.passed_count} ruling(s) passed, "
            f"{session.failed_count} failed.",
            "",
            "*This bulletin is the official record of the Grand Council of Guilds.*",
        ]

        return "\n".join(lines)

    # ── Discord posting ────────────────────────────────────────────────────

    async def _post_bulletin(self, session: CouncilSession, channel) -> None:
        """Post bulletin to Discord, splitting at 2000 chars if needed."""
        try:
            import discord
            text = session.bulletin_text

            # Split on ruling dividers if over 2000 chars
            if len(text) <= 1900:
                await channel.send(text)
                return

            # Split into chunks at ruling boundaries
            chunks = []
            current = ""
            for line in text.split("\n"):
                if len(current) + len(line) + 1 > 1900 and current:
                    chunks.append(current.strip())
                    current = line + "\n"
                else:
                    current += line + "\n"
            if current.strip():
                chunks.append(current.strip())

            for chunk in chunks:
                if chunk:
                    await channel.send(chunk)
                    await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"🏛️ Council bulletin post failed: {e}")

    # ── World change application ───────────────────────────────────────────

    def _load_decided_topics(self) -> list[dict]:
        """Load all previously decided rulings (pass or fail) from global_state."""
        from src.db_api import raw_query
        try:
            rows = raw_query(
                "SELECT state_value FROM global_state WHERE state_key = %s",
                (self._RULINGS_STATE_KEY,),
            )
            if rows and rows[0].get("state_value"):
                val = rows[0]["state_value"]
                return json.loads(val) if isinstance(val, str) else val
        except Exception as e:
            logger.warning(f"🏛️ Could not load decided topics: {e}")
        return []

    async def _apply_passed_rulings(self, all_rulings: list[CouncilRuling]) -> list[str]:
        """Persist ALL rulings (pass and fail) to DB so topics aren't repeated."""
        from src.db_api import raw_query, raw_execute
        applied = []

        existing = self._load_decided_topics()

        for ruling in all_rulings:
            record = {
                "date":      datetime.now().isoformat(),
                "topic":     ruling.topic,
                "proposal":  ruling.proposal,
                "votes_yes": ruling.votes_yes,
                "votes_no":  ruling.votes_no,
                "tiebreak":  ruling.tiebreak_used,
                "passed":    ruling.passed,
            }
            existing.append(record)

            # Post passed rulings to news_memory for world continuity
            if ruling.passed:
                try:
                    fact = (
                        f"Grand Council ruling PASSED: {ruling.topic} — "
                        f"{ruling.proposal[:200]}"
                    )
                    raw_execute(
                        "INSERT INTO news_memory (facts, news_type, created_at) "
                        "VALUES (%s, %s, NOW())",
                        (fact, "council_ruling"),
                    )
                    applied.append(f"Ruling enacted: {ruling.topic}")
                except Exception as e:
                    logger.warning(f"🏛️ Could not write ruling to news_memory: {e}")
            else:
                applied.append(f"Ruling rejected (recorded): {ruling.topic}")

        # Persist all rulings (keep last 200) in global_state
        try:
            payload = json.dumps(existing[-200:], ensure_ascii=False)
            exists = raw_query(
                "SELECT id FROM global_state WHERE state_key = %s",
                (self._RULINGS_STATE_KEY,),
            )
            if exists:
                raw_execute(
                    "UPDATE global_state SET state_value = %s WHERE state_key = %s",
                    (payload, self._RULINGS_STATE_KEY),
                )
            else:
                raw_execute(
                    "INSERT INTO global_state (state_key, state_value) VALUES (%s, %s)",
                    (self._RULINGS_STATE_KEY, payload),
                )
        except Exception as e:
            logger.warning(f"🏛️ Could not persist rulings to global_state: {e}")

        return applied

    # ── Journal ────────────────────────────────────────────────────────────

    def _write_journal(self, session: CouncilSession) -> None:
        """Append session summary to journal.txt."""
        try:
            journal = Path(__file__).resolve().parent.parent.parent / "logs" / "journal.txt"
            journal.parent.mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lines = [
                f"\n[{ts}] [COUNCIL] ══ GRAND COUNCIL SESSION ══",
                f"[{ts}] [COUNCIL] Date: {session.session_date}",
                f"[{ts}] [COUNCIL] Rulings: {session.passed_count} passed / {session.failed_count} failed",
            ]
            for r in session.rulings:
                result = "PASSED" if r.passed else "FAILED"
                lines.append(
                    f"[{ts}] [COUNCIL] [{result}] {r.topic}: {r.proposal[:100]}"
                )
            with open(journal, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception as e:
            logger.warning(f"🏛️ Journal write failed: {e}")
