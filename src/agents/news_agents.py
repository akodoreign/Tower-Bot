"""
src/agents/news_agents.py — News Editorial Agent System

Three specialized agents for the Undercity Dispatch:

1. NewsEditorAgent — Factual news with creative writing skills + fact-checking
2. GossipEditorAgent — Rumors and half-truths (NEVER saved to memory)
3. SportsColumnistAgent — Arena coverage across all dome venues

Each agent uses the BaseAgent framework and integrates:
- Creative writing principles from cw-prose-writing
- Fact-checking against NPC roster, gazetteer, graveyard
- Expandable bulletin support (preview + full content)
"""

from __future__ import annotations

import json
import random
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.agents.base import BaseAgent, AgentConfig, AgentResponse, ModelType

logger = logging.getLogger(__name__)

DOCS_DIR = Path(__file__).resolve().parent.parent.parent / "campaign_docs"
NPC_ROSTER = DOCS_DIR / "npc_roster.json"
NPC_GRAVEYARD = DOCS_DIR / "npc_graveyard.json"
CITY_GAZETTEER = DOCS_DIR / "city_gazetteer.json"
ARENA_VENUES = DOCS_DIR / "arena_venues.json"


# ---------------------------------------------------------------------------
# Fact Checker Mixin — Validates content against world state
# ---------------------------------------------------------------------------

class FactCheckerMixin:
    """
    Mixin providing fact-checking capabilities against world data.
    
    Checks:
    - NPC existence and status (alive/dead/faction)
    - Location validity (exists in gazetteer)
    - Arena venue accuracy
    """
    
    _cache: Dict[str, any] = {}
    
    @classmethod
    def _load_json(cls, path: Path, cache_key: str) -> Dict:
        """Load JSON with caching."""
        if cache_key not in cls._cache:
            try:
                cls._cache[cache_key] = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                cls._cache[cache_key] = {}
        return cls._cache[cache_key]
    
    @classmethod
    def clear_cache(cls):
        """Clear cached data (call when world state changes)."""
        cls._cache.clear()
    
    def get_npc_roster(self) -> List[Dict]:
        """Get all living NPCs from MySQL (alive + injured)."""
        if "roster" not in self._cache:
            try:
                from src.db_api import raw_query as _rq
                rows = _rq(
                    "SELECT name, faction, role, status, location, data_json FROM npcs "
                    "WHERE status IN ('alive', 'injured') ORDER BY name"
                )
                npcs = []
                for row in (rows or []):
                    npc = {"name": row["name"], "faction": row["faction"],
                           "role": row["role"], "status": row["status"],
                           "location": row["location"]}
                    dj = row.get("data_json") or {}
                    if isinstance(dj, str):
                        import json as _json
                        try:
                            dj = _json.loads(dj)
                        except Exception:
                            dj = {}
                    npc.update(dj)
                    npcs.append(npc)
                self._cache["roster"] = npcs
            except Exception:
                # Fallback to JSON file if DB unavailable
                data = self._load_json(NPC_ROSTER, "_roster_file")
                self._cache["roster"] = data if isinstance(data, list) else data.get("npcs", [])
        return self._cache["roster"]
    
    def get_npc_graveyard(self) -> List[Dict]:
        """Get all dead NPCs from MySQL (status=dead)."""
        if "graveyard" not in self._cache:
            try:
                from src.db_api import raw_query as _rq
                rows = _rq(
                    "SELECT name, faction, role, status, data_json FROM npcs "
                    "WHERE status = 'dead' ORDER BY name"
                )
                npcs = []
                for row in (rows or []):
                    npc = {"name": row["name"], "faction": row["faction"],
                           "role": row["role"], "status": "dead"}
                    dj = row.get("data_json") or {}
                    if isinstance(dj, str):
                        import json as _json
                        try:
                            dj = _json.loads(dj)
                        except Exception:
                            dj = {}
                    npc.update(dj)
                    npcs.append(npc)
                self._cache["graveyard"] = npcs
            except Exception:
                data = self._load_json(NPC_GRAVEYARD, "_graveyard_file")
                self._cache["graveyard"] = data if isinstance(data, list) else data.get("npcs", [])
        return self._cache["graveyard"]
    
    def get_locations(self) -> Dict:
        """Get city gazetteer from MySQL (falls back to file)."""
        if "gazetteer" not in self._cache:
            try:
                from src.db_api import raw_query as _rq
                rows = _rq("SELECT content_json FROM gazetteer LIMIT 1") or []
                if rows and rows[0].get("content_json"):
                    cj = rows[0]["content_json"]
                    self._cache["gazetteer"] = json.loads(cj) if isinstance(cj, str) else cj
                else:
                    raise ValueError("no gazetteer row")
            except Exception:
                self._cache["gazetteer"] = self._load_json(CITY_GAZETTEER, "_gaz_file")
        return self._cache["gazetteer"]
    
    def get_arena_venues(self) -> List[Dict]:
        """Get arena venues."""
        data = self._load_json(ARENA_VENUES, "venues")
        return data.get("venues", []) if isinstance(data, dict) else []
    
    def npc_exists(self, name: str) -> bool:
        """Check if NPC exists (alive or dead)."""
        name_lower = name.lower()
        for npc in self.get_npc_roster():
            if npc.get("name", "").lower() == name_lower:
                return True
        for npc in self.get_npc_graveyard():
            if npc.get("name", "").lower() == name_lower:
                return True
        return False
    
    def npc_is_alive(self, name: str) -> bool:
        """Check if NPC is alive (in roster, not graveyard)."""
        name_lower = name.lower()
        for npc in self.get_npc_roster():
            if npc.get("name", "").lower() == name_lower:
                return True
        return False
    
    def npc_is_dead(self, name: str) -> bool:
        """Check if NPC is dead (in graveyard)."""
        name_lower = name.lower()
        for npc in self.get_npc_graveyard():
            if npc.get("name", "").lower() == name_lower:
                return True
        return False
    
    def get_npc_faction(self, name: str) -> Optional[str]:
        """Get NPC's faction affiliation."""
        name_lower = name.lower()
        for npc in self.get_npc_roster():
            if npc.get("name", "").lower() == name_lower:
                return npc.get("faction")
        return None
    
    def location_exists(self, location: str) -> bool:
        """Check if location exists in gazetteer."""
        loc_lower = location.lower()
        gazetteer = self.get_locations()
        
        # Check districts
        for district in gazetteer.get("districts", []):
            if district.get("name", "").lower() == loc_lower:
                return True
            # Check landmarks within district
            for landmark in district.get("landmarks", []):
                if landmark.get("name", "").lower() == loc_lower:
                    return True
        return False
    
    def venue_exists(self, venue_name: str) -> bool:
        """Check if arena venue exists."""
        name_lower = venue_name.lower()
        for venue in self.get_arena_venues():
            if venue.get("name", "").lower() == name_lower:
                return True
            if venue.get("short_name", "").lower() == name_lower:
                return True
        return False
    
    def get_random_living_npc(self, faction: Optional[str] = None) -> Optional[Dict]:
        """Get a random living NPC, optionally filtered by faction."""
        npcs = self.get_npc_roster()
        if faction:
            npcs = [n for n in npcs if n.get("faction", "").lower() == faction.lower()]
        return random.choice(npcs) if npcs else None
    
    def get_random_venue(self, event_type: Optional[str] = None) -> Optional[Dict]:
        """Get a random arena venue, optionally filtered by event type."""
        venues = self.get_arena_venues()
        if event_type:
            venues = [v for v in venues if event_type in v.get("event_types", [])]
        return random.choice(venues) if venues else None
    
    def build_fact_check_context(self) -> str:
        """Build a context string with key world facts for the LLM."""
        # Get sample NPCs
        npcs = self.get_npc_roster()[:20]  # Top 20 NPCs
        npc_names = [f"{n.get('name')} ({n.get('faction', 'Independent')})" for n in npcs]
        
        # Get dead NPCs (important to not resurrect)
        dead = self.get_npc_graveyard()[:10]
        dead_names = [n.get("name", "Unknown") for n in dead]
        
        # Get venues
        venues = self.get_arena_venues()
        venue_names = [v.get("short_name") or v.get("name") for v in venues]
        
        lines = [
            "FACT CHECK REFERENCE:",
            f"Living NPCs include: {', '.join(npc_names[:10])}",
            f"DEAD (do not use as living): {', '.join(dead_names)}" if dead_names else "",
            f"Arena venues: {', '.join(venue_names)}",
        ]
        return "\n".join(line for line in lines if line)


# ---------------------------------------------------------------------------
# Prose Style Constants — From cw-prose-writing skill
# ---------------------------------------------------------------------------

PROSE_PRINCIPLES = """
WRITING PRINCIPLES (enforce these):

1. BE SPECIFIC — Names, numbers, locations. "Cobbleway Market" not "a market."
2. GROUND BEFORE DRAMATIZE — Physical details first, emotions second.
3. ONE THING AT A TIME — Short sentences. One image per sentence.
4. CUT THE FLUFF — No "It is worth noting", "Interestingly", "Needless to say."
5. NO PURPLE PROSE — No "ethereal", "otherworldly", "ancient secrets."

BANNED PHRASES:
- "whispers of ancient secrets"
- "a chill ran down spines"  
- "something terrible was about to happen"
- "as the saying goes"
- "it goes without saying"

VOICE: Cynical but not hopeless. Wry. Dark humor. The reporter has seen too much.
"""

GOSSIP_VOICE = """
GOSSIP COLUMN VOICE:

You are the Undercity's most unreliable narrator. You deal in:
- Rumors that might be true
- Half-truths with a grain of accuracy
- Speculation presented as "sources say"
- Conspiracy theories that are entertaining
- Wild accusations (with plausible deniability)

STYLE:
- Breathless and conspiratorial
- Heavy use of "allegedly", "some say", "word on the street"
- Imply more than you state
- Leave readers wondering what's true
- Occasionally mix in an actual fact to keep them guessing

TONE: Tabloid energy. Gossip rag. The kind of news that spreads in whispers.
"""

SPORTS_VOICE = """
SPORTS COLUMNIST VOICE:

You are the Undercity's premier sports commentator. You cover:
- Combat bouts at all arena venues
- Beast races and creature shows
- Magical duels and divine trials
- Construct fights and salvage sports
- Rankings, upsets, drama

STYLE:
- Enthusiastic but knowledgeable
- Know the fighters, beasts, and venues by heart
- Mix stats with personality
- Call out upsets and drama
- Build narratives around rivalries
- Reference venue-specific atmosphere

TONE: Sports broadcaster energy. Color commentary. Makes every event feel important.
"""


# ---------------------------------------------------------------------------
# Bulletin Result Dataclass
# ---------------------------------------------------------------------------

@dataclass
class BulletinResult:
    """Result from a news agent bulletin generation."""
    preview: str           # 3-line preview for Discord embed
    full_content: str      # Full expandable content
    headline: str          # Short headline
    bulletin_type: str     # "news", "gossip", "sports"
    save_to_memory: bool   # Whether to save to news_memory.txt
    source_attribution: str  # e.g. "— TNN Field Correspondent"
    venue: Optional[str] = None  # For sports, which venue
    success: bool = True
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# News Editor Agent — Factual News
# ---------------------------------------------------------------------------

class NewsEditorAgent(BaseAgent, FactCheckerMixin):
    """
    Factual news editor with creative writing skills and fact-checking.
    
    Produces grounded, specific news bulletins that:
    - Use real NPCs, locations, factions
    - Avoid purple prose and AI clichés
    - Are fact-checked against world state
    - ARE saved to memory for continuity
    """
    
    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name="qwen3-8b-slim:latest",
            model_type=ModelType.LOCAL,
            timeout=180.0,
            max_retries=2,
            temperature=0.7,
            max_tokens=2048,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        fact_context = self.build_fact_check_context()
        
        prompt = f"""You are the Senior Editor of the Undercity Dispatch, the Tower's only reliable news source.

{PROSE_PRINCIPLES}

{fact_context}

YOUR JOB:
- Write factual news bulletins about events in the Undercity
- Use REAL NPCs and locations from the reference above
- NEVER use dead NPCs as if they were alive
- Keep bulletins to 4-8 lines (preview will be first 3 lines)
- End with a correspondent attribution

FORMAT:
📰 **[DISTRICT/TOPIC] — [HEADLINE]**
[News content - specific, grounded, no fluff]
-# *— TNN Field Correspondent*
"""
        if context:
            prompt += f"\n\nADDITIONAL CONTEXT:\n{context}"
        
        return prompt
    
    async def generate_bulletin(
        self,
        news_type: str,
        instruction: str,
        context: Optional[str] = None,
    ) -> BulletinResult:
        """Generate a fact-checked news bulletin."""
        prompt = f"Write a {news_type} news bulletin.\n\nINSTRUCTION: {instruction}"
        
        response = await self.complete(prompt, context=context)
        
        if not response.success:
            return BulletinResult(
                preview="",
                full_content="",
                headline="",
                bulletin_type="news",
                save_to_memory=True,
                source_attribution="— TNN Field Correspondent",
                success=False,
                error=response.error,
            )
        
        content = response.content.strip()
        lines = content.split("\n")
        
        # Extract headline from first line if present
        headline = ""
        if lines and "**" in lines[0]:
            headline = lines[0].replace("📰", "").replace("**", "").strip()
        
        # Preview is first 3 non-empty lines
        preview_lines = [l for l in lines if l.strip()][:3]
        preview = "\n".join(preview_lines)
        
        return BulletinResult(
            preview=preview,
            full_content=content,
            headline=headline,
            bulletin_type="news",
            save_to_memory=True,  # News IS saved
            source_attribution="— TNN Field Correspondent",
            success=True,
        )


# ---------------------------------------------------------------------------
# Gossip Editor Agent — Rumors and Half-Truths
# ---------------------------------------------------------------------------

class GossipEditorAgent(BaseAgent, FactCheckerMixin):
    """
    Gossip columnist dealing in rumors and half-truths.
    
    Produces unreliable but entertaining content that:
    - Mixes truth with speculation
    - Uses "allegedly", "sources say", "word is"
    - May reference real NPCs but in unverified contexts
    - Is NOT saved to memory (prevents pollution)
    """
    
    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name="qwen3-8b-slim:latest",
            model_type=ModelType.LOCAL,
            timeout=180.0,
            max_retries=2,
            temperature=0.85,  # Higher temperature for more creative rumors
            max_tokens=2048,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        # Get some real NPCs to potentially reference
        npcs = self.get_npc_roster()[:15]
        npc_names = [n.get("name") for n in npcs]
        
        prompt = f"""You are the anonymous writer behind "Whispers in the Dark", the Undercity's most scandalous gossip column.

{GOSSIP_VOICE}

REAL NPCs (mix these into rumors, true or not):
{', '.join(npc_names)}

YOUR JOB:
- Write gossip, rumors, and speculation
- Mix real names with wild accusations
- Use "allegedly", "sources claim", "word on the street"
- Some items might be TRUE. Most are exaggerated.
- Keep bulletins to 4-8 lines (preview will be first 3 lines)
- End with your anonymous signature

FORMAT:
👁️ **WHISPERS IN THE DARK**
[Scandalous gossip - breathless, conspiratorial, unreliable]
-# *— A friend who knows things*
"""
        if context:
            prompt += f"\n\nSEED THIS RUMOR AROUND:\n{context}"
        
        return prompt
    
    async def generate_bulletin(
        self,
        topic: Optional[str] = None,
        seed_npc: Optional[str] = None,
        context: Optional[str] = None,
    ) -> BulletinResult:
        """Generate a gossip bulletin (NOT saved to memory)."""
        prompt = "Write a gossip column item."
        if topic:
            prompt += f"\n\nTOPIC: {topic}"
        if seed_npc:
            prompt += f"\n\nMENTION THIS NPC: {seed_npc}"
        
        response = await self.complete(prompt, context=context)
        
        if not response.success:
            return BulletinResult(
                preview="",
                full_content="",
                headline="Whispers in the Dark",
                bulletin_type="gossip",
                save_to_memory=False,
                source_attribution="— A friend who knows things",
                success=False,
                error=response.error,
            )
        
        content = response.content.strip()
        lines = content.split("\n")
        
        preview_lines = [l for l in lines if l.strip()][:3]
        preview = "\n".join(preview_lines)
        
        return BulletinResult(
            preview=preview,
            full_content=content,
            headline="Whispers in the Dark",
            bulletin_type="gossip",
            save_to_memory=False,  # Gossip is NOT saved
            source_attribution="— A friend who knows things",
            success=True,
        )


# ---------------------------------------------------------------------------
# Sports Columnist Agent — Arena Coverage
# ---------------------------------------------------------------------------

class SportsColumnistAgent(BaseAgent, FactCheckerMixin):
    """
    Sports columnist covering arena events across all dome venues.
    
    Produces exciting sports coverage that:
    - Covers combat, racing, beast shows, magical duels
    - Knows all venues and their flavor
    - Builds narratives around fighters and rivalries
    - IS saved to memory for continuity
    """
    
    def _get_config(self) -> AgentConfig:
        return AgentConfig(
            model_name="qwen3-8b-slim:latest",
            model_type=ModelType.LOCAL,
            timeout=180.0,
            max_retries=2,
            temperature=0.75,
            max_tokens=2048,
        )
    
    def _build_system_prompt(self, context: Optional[str] = None) -> str:
        # Get venue information
        venues = self.get_arena_venues()
        venue_info = []
        for v in venues:
            events = ", ".join(v.get("event_types", [])[:3])
            flavor = v.get("flavor", {}).get("atmosphere", "")
            venue_info.append(f"- {v.get('short_name', v.get('name'))}: {events}. {flavor}")
        
        prompt = f"""You are Vox Ferrum, the Undercity's legendary sports columnist.

{SPORTS_VOICE}

ARENA VENUES:
{chr(10).join(venue_info)}

YOUR JOB:
- Write exciting sports coverage
- Cover combat, racing, beast shows, magical duels, construct fights
- Know the venues and their unique atmosphere
- Build narratives around fighters, beasts, and rivalries
- Mix results with color commentary
- Keep bulletins to 4-8 lines (preview will be first 3 lines)
- End with your signature

FORMAT:
🏟️ **[VENUE] — [EVENT TYPE]**
[Exciting sports coverage - stats, drama, atmosphere]
-# *— Vox Ferrum, Arena Correspondent*
"""
        if context:
            prompt += f"\n\nCOVER THIS EVENT:\n{context}"
        
        return prompt
    
    async def generate_bulletin(
        self,
        event_type: Optional[str] = None,
        venue: Optional[str] = None,
        context: Optional[str] = None,
    ) -> BulletinResult:
        """Generate a sports bulletin."""
        # Pick a random venue if not specified
        if not venue:
            venue_data = self.get_random_venue(event_type)
            if venue_data:
                venue = venue_data.get("short_name") or venue_data.get("name")
        
        prompt = "Write a sports column covering an arena event."
        if event_type:
            prompt += f"\n\nEVENT TYPE: {event_type}"
        if venue:
            prompt += f"\n\nVENUE: {venue}"
        
        response = await self.complete(prompt, context=context)
        
        if not response.success:
            return BulletinResult(
                preview="",
                full_content="",
                headline="Arena Report",
                bulletin_type="sports",
                save_to_memory=True,
                source_attribution="— Vox Ferrum, Arena Correspondent",
                venue=venue,
                success=False,
                error=response.error,
            )
        
        content = response.content.strip()
        lines = content.split("\n")
        
        # Extract headline
        headline = "Arena Report"
        if lines and "**" in lines[0]:
            headline = lines[0].replace("🏟️", "").replace("**", "").strip()
        
        preview_lines = [l for l in lines if l.strip()][:3]
        preview = "\n".join(preview_lines)
        
        return BulletinResult(
            preview=preview,
            full_content=content,
            headline=headline,
            bulletin_type="sports",
            save_to_memory=True,  # Sports IS saved
            source_attribution="— Vox Ferrum, Arena Correspondent",
            venue=venue,
            success=True,
        )


# ---------------------------------------------------------------------------
# Agent Factory — Easy instantiation
# ---------------------------------------------------------------------------

def get_news_agent(agent_type: str) -> BaseAgent:
    """Factory function to get a news agent by type."""
    agents = {
        "news": NewsEditorAgent,
        "editor": NewsEditorAgent,
        "gossip": GossipEditorAgent,
        "rumor": GossipEditorAgent,
        "sports": SportsColumnistAgent,
        "arena": SportsColumnistAgent,
    }
    agent_class = agents.get(agent_type.lower())
    if not agent_class:
        raise ValueError(f"Unknown agent type: {agent_type}. Valid: {list(agents.keys())}")
    return agent_class()


# ---------------------------------------------------------------------------
# Convenience Functions
# ---------------------------------------------------------------------------

async def generate_news_bulletin(
    news_type: str,
    instruction: str,
    context: Optional[str] = None,
) -> BulletinResult:
    """Generate a factual news bulletin."""
    agent = NewsEditorAgent()
    try:
        return await agent.generate_bulletin(news_type, instruction, context)
    finally:
        await agent.close()


async def generate_gossip_bulletin(
    topic: Optional[str] = None,
    seed_npc: Optional[str] = None,
    context: Optional[str] = None,
) -> BulletinResult:
    """Generate a gossip bulletin (NOT saved to memory)."""
    agent = GossipEditorAgent()
    try:
        return await agent.generate_bulletin(topic, seed_npc, context)
    finally:
        await agent.close()


async def generate_sports_bulletin(
    event_type: Optional[str] = None,
    venue: Optional[str] = None,
    context: Optional[str] = None,
) -> BulletinResult:
    """Generate a sports bulletin."""
    agent = SportsColumnistAgent()
    try:
        return await agent.generate_bulletin(event_type, venue, context)
    finally:
        await agent.close()
