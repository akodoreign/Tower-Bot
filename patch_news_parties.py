"""
patch_news_parties.py
Wires party profiles into the news_feed bulletin generator.

What this adds:
  1. _load_party_bulletin_context() — loads 1-3 random generated party profiles,
     returns (party_context_block, party_list) for prompt injection.

  2. Dynamic injection in _build_prompt() — when profiles exist, adds 6 story-angle
     bulletin types seeded with real member names, roles, and affiliations from the
     actual saved profiles. The AI writes about real people, not invented ones.

  3. Party context block injected into the prompt so Mistral knows who it's
     writing about — same pattern as NPC injury/conflict injection.

Run once from the bot root:
  cd C:\\Users\\akodoreign\\Desktop\\chatGPT-discord-bot
  python patch_news_parties.py
Then delete this file and restart the bot.
"""

from pathlib import Path

path = Path(__file__).parent / "src" / "news_feed.py"
content = path.read_text(encoding="utf-8")
original = content
applied = 0

# ─────────────────────────────────────────────────────────────────────────────
# PATCH 1
# Insert _load_party_bulletin_context() right before _build_prompt()
# ─────────────────────────────────────────────────────────────────────────────

ANCHOR = "def _build_prompt(memory_entries: List[str]) -> str:"

NEW_FUNC = '''\
def _load_party_bulletin_context() -> tuple:
    """
    Load 1-3 random generated party profiles for bulletin prompt injection.
    Returns (party_context_block: str, parties: list[dict]).
    Only returns profiles where generated=True so the AI always has real names.
    """
    try:
        from src.party_profiles import PARTY_PROFILE_DIR
        import json as _json
        profiles = []
        for f in PARTY_PROFILE_DIR.glob("*.json"):
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                if data.get("generated") and data.get("name") and data.get("members"):
                    profiles.append(data)
            except Exception:
                pass
        if not profiles:
            return "", []
        # Pick 1-3 at random — enough to enable inter-party story angles
        chosen = random.sample(profiles, min(3, len(profiles)))
        lines = ["KNOWN ADVENTURER PARTIES (use these for party-focused bulletins — real people, real names):"]
        for p in chosen:
            tier   = p.get("tier", "Unknown")
            affil  = p.get("affiliation", "No Affiliation")
            spec   = p.get("specialty", "")
            rep    = p.get("reputation_note", "")
            members = p.get("members", [])
            mline  = " | ".join(f"{m['name']} ({m['role']}, {m.get('species','?')})" for m in members)
            lines.append(f"  PARTY: {p['name']}  [{tier} rank | {affil}]")
            if spec:
                lines.append(f"    Specialty: {spec}")
            if mline:
                lines.append(f"    Members: {mline}")
            for m in members:
                if m.get("note"):
                    lines.append(f"    {m['name']}: {m['note']}")
            if rep:
                lines.append(f"    City reputation: {rep}")
        return "\\n".join(lines), chosen
    except Exception:
        return "", []


'''

if ANCHOR in content:
    content = content.replace(ANCHOR, NEW_FUNC + ANCHOR, 1)
    applied += 1
    print("PATCH 1 (_load_party_bulletin_context): OK")
else:
    print("PATCH 1: ANCHOR NOT FOUND — check that _build_prompt is still present")


# ─────────────────────────────────────────────────────────────────────────────
# PATCH 2
# Inside _build_prompt(), inject party context + party bulletin types
# right before the final return statement.
# Anchor: the closing comment block just before the return.
# ─────────────────────────────────────────────────────────────────────────────

# We'll insert after the alive_roster/inter-NPC injection block.
# Anchor: the last thing added before the return f"""..."""

OLD_RETURN_ANCHOR = "    return f\"\"\"{_WORLD_LORE}"

NEW_PARTY_INJECT = '''\
    # ---- Party bulletin types — dynamically injected from real saved profiles ----
    # Loaded fresh each call so new profiles from gear runs are immediately available.
    party_context_block, party_list = _load_party_bulletin_context()
    if party_list:
        for p in party_list:
            pname   = p.get("name", "a party")
            affil   = p.get("affiliation", "No Affiliation")
            spec    = p.get("specialty", "their work")
            members = p.get("members", [])
            # Pick 1-2 named members for targeted story seeds
            named   = [m["name"] for m in members[:2]] if members else []
            named_str = named[0] if len(named) == 1 else (
                f"{named[0]} or {named[1]}" if len(named) >= 2 else pname
            )
            member_roles = {m["name"]: m["role"] for m in members}
            all_types += [
                # Off-duty sighting
                f"a street sighting or overheard moment involving a member of {pname} "
                f"({affil}) — something personal, off-duty, or out of character for their "
                f"reputation. Focus on {named_str} if possible. Small and specific.",

                # Internal tension / rumour
                f"a rumour circulating about {pname} — internal tension, something their "
                f"affiliation ({affil}) doesn't know, or whispers about their last job. "
                f"Keep it ambiguous. Name a real member if it fits.",

                # Member profile / spotlight
                f"a brief street-press profile piece on {named_str} from {pname} "
                f"({member_roles.get(named_str, 'member')}) — something the Undercity has "
                f"noticed about them lately. Their habit, their look, their reputation on the street.",

                # Public incident
                f"a public incident or visible moment involving {pname} — an argument, "
                f"a visible celebration, tension after a hard contract, or something a "
                f"bystander witnessed and reported to the Dispatch. Specific location.",

                # Faction memo / professional notice
                f"a short faction notice or memo referencing {pname}'s recent work — "
                f"from {affil if affil != 'No Affiliation' else 'the Adventurers Guild or a local faction'}. "
                f"Could be praise, a quiet concern, a warning, or a new assignment offer.",
            ]
        # Inter-party story if we have 2+ parties
        if len(party_list) >= 2:
            pa = party_list[0].get("name", "one party")
            pb = party_list[1].get("name", "another party")
            all_types += [
                f"an inter-party moment: {pa} and {pb} crossed paths somewhere in the city — "
                f"what happened between them. An argument over a contract, a favour exchanged, "
                f"a tense silence. Name real members. Keep the outcome ambiguous.",
            ]

    '''  # note: trailing spaces intentional — matches Python indent of return block

NEW_RETURN = NEW_PARTY_INJECT + "    return f\"\"\"{_WORLD_LORE}"

if OLD_RETURN_ANCHOR in content:
    # Replace only the FIRST occurrence (the one inside _build_prompt)
    content = content.replace(OLD_RETURN_ANCHOR, NEW_RETURN, 1)
    applied += 1
    print("PATCH 2 (party inject in _build_prompt): OK")
else:
    print("PATCH 2: ANCHOR NOT FOUND — the return f-string may have changed")


# ─────────────────────────────────────────────────────────────────────────────
# PATCH 3
# Inject party_context_block into the prompt f-string so Mistral actually
# sees the party data. Insert it right after the {npc_status_block} injection.
# ─────────────────────────────────────────────────────────────────────────────

OLD_PROMPT_BODY = "{npc_status_block}\n{mission_block}{recent_block}"
NEW_PROMPT_BODY = "{npc_status_block}\n{party_context_block}\n{mission_block}{recent_block}"

if OLD_PROMPT_BODY in content:
    content = content.replace(OLD_PROMPT_BODY, NEW_PROMPT_BODY, 1)
    applied += 1
    print("PATCH 3 (party_context_block in prompt f-string): OK")
else:
    print("PATCH 3: ANCHOR NOT FOUND — check {npc_status_block} placement in the f-string")


# ─────────────────────────────────────────────────────────────────────────────
# Write back
# ─────────────────────────────────────────────────────────────────────────────

if content != original:
    path.write_text(content, encoding="utf-8")
    print(f"\nnews_feed.py updated — {applied}/3 patches applied.")
    print("Restart the bot to pick up changes. Delete this file when done.")
else:
    print("\nNo changes written — all anchors may have been missing.")
