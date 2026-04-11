"""
npc_lookup.py — Fuzzy NPC name lookup for /chat and /draw commands.

When a user puts an NPC name in quotes (e.g., "Serrik Dhal"), this module:
1. Extracts the quoted string
2. Fuzzy-matches it against the NPC roster
3. Returns the NPC data and/or appearance info for injection into prompts

Usage:
    from src.npc_lookup import extract_and_lookup_npcs, get_npc_context_for_prompt
    
    # Extract quoted names and look them up
    matches = extract_and_lookup_npcs(user_message)
    # Returns: [{"name": "Serrik Dhal", "data": {...}, "appearance": {...}, "sd_prompt": "..."}, ...]
    
    # Get formatted context for AI prompt injection
    context = get_npc_context_for_prompt(user_message)
    # Returns: "NPC REFERENCE: Serrik Dhal - Human male, Guildmaster of Iron Fang Consortium..."
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from difflib import SequenceMatcher

from src.log import logger

DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"
NPC_ROSTER_FILE = DOCS_DIR / "npc_roster.json"
NPC_GRAVEYARD_FILE = DOCS_DIR / "npc_graveyard.json"
NPC_APP_DIR = DOCS_DIR / "npc_appearances"

# Minimum similarity threshold for fuzzy matching (0.0 to 1.0)
FUZZY_THRESHOLD = 0.6


def _load_all_npcs() -> List[Dict]:
    """Load all NPCs from MySQL npcs table (falls back to JSON files)."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT name, faction, role, status, location, data_json FROM npcs ORDER BY name") or []
        if rows:
            npcs = []
            for row in rows:
                dj = row.get("data_json") or {}
                if isinstance(dj, str):
                    try:
                        dj = json.loads(dj)
                    except Exception:
                        dj = {}
                npc = {**dj, "name": row["name"], "faction": row["faction"],
                       "role": row["role"], "status": row["status"], "location": row["location"],
                       "_source": "graveyard" if row["status"] == "dead" else "roster"}
                npcs.append(npc)
            return npcs
    except Exception as e:
        logger.warning(f"npc_lookup: DB load failed: {e}")

    npcs = []
    if NPC_ROSTER_FILE.exists():
        try:
            roster = json.loads(NPC_ROSTER_FILE.read_text(encoding="utf-8"))
            for npc in roster:
                npc["_source"] = "roster"
            npcs.extend(roster)
        except Exception as e:
            logger.warning(f"npc_lookup: Could not load roster: {e}")

    if NPC_GRAVEYARD_FILE.exists():
        try:
            graveyard = json.loads(NPC_GRAVEYARD_FILE.read_text(encoding="utf-8"))
            for npc in graveyard:
                npc["_source"] = "graveyard"
                npc["status"] = "dead"
            npcs.extend(graveyard)
        except Exception as e:
            logger.warning(f"npc_lookup: Could not load graveyard: {e}")

    return npcs


def _get_npc_appearance(name: str) -> Optional[Dict]:
    """Load appearance data for an NPC from MySQL npc_appearances (falls back to file)."""
    try:
        from src.db_api import raw_query as _rq
        rows = _rq(
            "SELECT appearance_prompt, sd_prompt, appearance_json FROM npc_appearances WHERE npc_name = %s LIMIT 1",
            (name,)
        ) or []
        if rows:
            row = rows[0]
            aj = row.get("appearance_json") or {}
            if isinstance(aj, str):
                try:
                    aj = json.loads(aj)
                except Exception:
                    aj = {}
            result = dict(aj)
            if row.get("sd_prompt"):
                result["sd_prompt"] = row["sd_prompt"]
            if row.get("appearance_prompt"):
                result["physical"] = row["appearance_prompt"]
            return result if result else None
    except Exception as e:
        logger.warning(f"npc_lookup: appearance DB lookup failed for {name}: {e}")
    # Fallback to file
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    app_file = NPC_APP_DIR / f"{slug}.json"
    if app_file.exists():
        try:
            return json.loads(app_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _similarity(a: str, b: str) -> float:
    """Calculate similarity ratio between two strings (case-insensitive)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _fuzzy_match_npc(query: str, npcs: List[Dict]) -> Optional[Tuple[Dict, float]]:
    """
    Find the best matching NPC for a query string.
    Returns (npc_data, similarity_score) or None if no match above threshold.
    """
    query_lower = query.lower().strip()
    best_match = None
    best_score = 0.0
    
    for npc in npcs:
        name = npc.get("name", "")
        if not name:
            continue
        
        name_lower = name.lower()
        
        # Exact match (case-insensitive)
        if query_lower == name_lower:
            return (npc, 1.0)
        
        # Check if query is contained in name or vice versa
        if query_lower in name_lower or name_lower in query_lower:
            score = 0.9
            if score > best_score:
                best_score = score
                best_match = npc
            continue
        
        # Fuzzy match
        score = _similarity(query, name)
        
        # Also try matching against first name only
        first_name = name.split()[0] if " " in name else name
        first_score = _similarity(query, first_name)
        score = max(score, first_score)
        
        # Also try matching against last name only
        if " " in name:
            last_name = name.split()[-1]
            last_score = _similarity(query, last_name)
            score = max(score, last_score)
        
        if score > best_score:
            best_score = score
            best_match = npc
    
    if best_match and best_score >= FUZZY_THRESHOLD:
        return (best_match, best_score)
    
    return None


def extract_quoted_names(text: str) -> List[str]:
    """
    Extract all quoted strings from text.
    Matches both "double quotes" and 'single quotes'.
    """
    # Match content inside double or single quotes
    pattern = r'["\']([^"\']+)["\']'
    matches = re.findall(pattern, text)
    return [m.strip() for m in matches if m.strip()]


def extract_and_lookup_npcs(text: str) -> List[Dict]:
    """
    Extract quoted names from text and look them up in the NPC roster.
    
    Returns a list of dicts with:
        - name: The canonical NPC name
        - query: What the user typed
        - confidence: Match confidence (0.0 to 1.0)
        - data: Full NPC data from roster
        - appearance: Appearance data if available
        - sd_prompt: Stable Diffusion prompt if available
        - status: "alive", "injured", or "dead"
    """
    quoted = extract_quoted_names(text)
    if not quoted:
        return []
    
    npcs = _load_all_npcs()
    results = []
    seen_names = set()
    
    for query in quoted:
        match = _fuzzy_match_npc(query, npcs)
        if match:
            npc, confidence = match
            name = npc.get("name", query)
            
            # Skip duplicates
            if name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            
            # Get appearance data
            appearance = _get_npc_appearance(name)
            sd_prompt = appearance.get("sd_prompt", "") if appearance else ""
            
            results.append({
                "name": name,
                "query": query,
                "confidence": confidence,
                "data": npc,
                "appearance": appearance,
                "sd_prompt": sd_prompt,
                "status": npc.get("status", "alive"),
            })
            
            logger.info(
                f"npc_lookup: '{query}' → '{name}' (confidence: {confidence:.2f})"
            )
        else:
            logger.debug(f"npc_lookup: No match for '{query}'")
    
    return results


def get_npc_context_for_prompt(text: str, include_appearance: bool = True) -> str:
    """
    Extract NPC references from text and build a context block for AI prompt injection.
    
    Used by /chat to give the AI context about mentioned NPCs.
    
    Args:
        text: User message text
        include_appearance: Whether to include physical appearance details
    
    Returns:
        Formatted context string, or empty string if no NPCs found
    """
    matches = extract_and_lookup_npcs(text)
    if not matches:
        return ""
    
    lines = ["", "NPC REFERENCE (from city records — use this info when answering):"]
    
    for m in matches:
        npc = m["data"]
        name = m["name"]
        status = m["status"]
        
        # Basic info
        species = npc.get("species", "Unknown")
        faction = npc.get("faction", "Independent")
        rank = npc.get("rank", "")
        role = npc.get("role", "")
        location = npc.get("location", "")
        
        # Build description line
        desc_parts = [f"**{name}**"]
        if status == "dead":
            desc_parts.append("[DECEASED]")
        elif status == "injured":
            desc_parts.append("[INJURED]")
        
        desc_parts.append(f"— {species}")
        if rank:
            desc_parts.append(f", {rank}")
        desc_parts.append(f"of {faction}")
        
        lines.append(" ".join(desc_parts))
        
        if role:
            lines.append(f"  Role: {role}")
        if location:
            lines.append(f"  Location: {location}")
        
        # Motivation/personality
        if npc.get("motivation"):
            lines.append(f"  Motivation: {npc['motivation']}")
        
        # Secrets (if revealed or for DM context)
        if npc.get("revealed_secrets"):
            lines.append(f"  Known secrets: {'; '.join(npc['revealed_secrets'])}")
        
        # Appearance (if requested and available)
        if include_appearance and m.get("appearance"):
            app = m["appearance"]
            if app.get("physical"):
                # Just first sentence of physical description
                phys = app["physical"].split(".")[0].strip()
                lines.append(f"  Appearance: {phys}.")
            if app.get("style_summary"):
                lines.append(f"  Style: {app['style_summary']}")
        
        lines.append("")  # Blank line between NPCs
    
    return "\n".join(lines)


def get_npc_sd_prompt(text: str) -> str:
    """
    Extract NPC references and build a Stable Diffusion prompt fragment.
    
    Used by /draw to inject NPC appearance into image generation.
    
    Returns:
        SD prompt fragment with NPC appearance details, or empty string
    """
    matches = extract_and_lookup_npcs(text)
    if not matches:
        return ""
    
    prompt_parts = []
    
    for m in matches[:3]:  # Limit to 3 NPCs for prompt length
        if m.get("sd_prompt"):
            # Use the pre-generated SD prompt
            prompt_parts.append(m["sd_prompt"].split(".")[0].strip())
        elif m.get("appearance"):
            # Build from appearance data
            app = m["appearance"]
            if app.get("sd_prompt"):
                prompt_parts.append(app["sd_prompt"].split(".")[0].strip())
            elif app.get("physical"):
                prompt_parts.append(app["physical"].split(".")[0].strip())
        else:
            # Fallback to roster data
            npc = m["data"]
            species = npc.get("species", "human")
            basic = f"{species}"
            if npc.get("appearance"):
                basic = npc["appearance"].split(".")[0].strip()
            prompt_parts.append(basic)
    
    return ", ".join(prompt_parts) if prompt_parts else ""


def lookup_npc_by_name(name: str) -> Optional[Dict]:
    """
    Direct lookup of an NPC by name (with fuzzy matching).
    
    Returns the full NPC data dict or None if not found.
    """
    npcs = _load_all_npcs()
    match = _fuzzy_match_npc(name, npcs)
    if match:
        npc, confidence = match
        # Add appearance data
        appearance = _get_npc_appearance(npc.get("name", name))
        npc["_appearance"] = appearance
        npc["_match_confidence"] = confidence
        return npc
    return None


# ─── CLI test ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        test_text = " ".join(sys.argv[1:])
    else:
        test_text = 'Tell me about "Serik Dhal" and "Captain Korin"'
    
    print(f"Input: {test_text}")
    print("-" * 40)
    
    matches = extract_and_lookup_npcs(test_text)
    for m in matches:
        print(f"Query: '{m['query']}' → '{m['name']}' ({m['confidence']:.2f})")
        print(f"  Status: {m['status']}")
        print(f"  Faction: {m['data'].get('faction', '?')}")
        if m.get("sd_prompt"):
            print(f"  SD: {m['sd_prompt'][:80]}...")
        print()
    
    print("-" * 40)
    print("Context block:")
    print(get_npc_context_for_prompt(test_text))
