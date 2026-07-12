"""
npc_knowledge_cards.py — Per-NPC DM reference cards for mission modules.

For every named NPC in a mission scene, generates a compact card:
  - What they know for certain (role + faction inference)
  - What they may know (mission-specific)
  - What they will not say (motivation / secret hint)
  - Tone (how they speak — faction + role derived)
  - Their words (quote from DB, or motivation-derived sample)

Call pattern:
    from src.mission_builder.npc_knowledge_cards import build_npc_cards_html
    html = build_npc_cards_html(npc_names, mission, scenes)
"""

from __future__ import annotations

import html as _html
import json
import random
import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Faction → tone descriptor
# ---------------------------------------------------------------------------

_FACTION_TONE: Dict[str, str] = {
    "Iron Fang Consortium":   "transactional and controlled — implies consequences rather than stating them; never raises voice",
    "Argent Blades":          "direct and professional — respects competence, brief with people who waste time",
    "Wardens of Ash":         "measured and duty-bound — pauses before answering; treats information as a resource to be rationed",
    "Serpent Choir":          "deliberate and contractual — every sentence sounds like it could be cited later",
    "Obsidian Lotus":         "cold and unhurried — delivers information the way a surgeon delivers a diagnosis",
    "Glass Sigil":            "precise and archival — qualifies every statement; hates being misquoted",
    "Patchwork Saints":       "direct and warm without being naive — names the problem before asking for help",
    "Adventurers Guild":      "pragmatic and slightly bored — has heard every version of this before",
    "Guild of Ashen Scrolls": "formal and careful — treats rumour and fact as different categories and says so",
    "Tower Authority":        "bureaucratic and clipped — what they don't say matters more than what they do",
    "Independent":            "variable — reads the room, adjusts; not tied to a house style",
    "Brother Thane's Cult":   "fervent and patient — believes they are doing you a favour by talking to you",
    "Wizards Tower":          "abstract and precise — uses discipline-specific language without apology",
    "Leaden Crown":           "hierarchical and formal — title-conscious; respects rank above relationship",
}

_GUILD_TONE = "corporate and level — aware of liability; carefully phrases things as information rather than advice"

_ROLE_TONE: Dict[str, str] = {
    "enforcer":    "flat and economical — says the minimum that gets the result; silence is also a tool",
    "archivist":   "careful and qualified — 'to my knowledge', 'as of last record', 'I cannot confirm'",
    "merchant":    "calculating and pleasant — the warmth is real but the math is always running",
    "informant":   "indirect and conditional — everything comes with a cost that isn't always named upfront",
    "healer":      "direct about facts, gentle about consequences — doesn't soften the prognosis but eases the delivery",
    "courier":     "brief and route-minded — thinking about the next three steps before the current one is done",
    "scholar":     "enthusiastic and distracting — gives more context than was asked for",
    "priest":      "measured and interpretive — frames events in a larger pattern even when you didn't ask for one",
    "assassin":    "minimal and watchful — the fewer words the better; eye contact is assessment",
    "criminal":    "cautious and transactional — never confirms, never denies; costs before answers",
    "officer":     "precise and hierarchical — what they know is filtered through what they're allowed to share",
    "clerk":       "procedural and slightly detached — the process is more real to them than the outcome",
    "spy":         "pleasant and specific — the warmth is weaponised; every question has a purpose",
    "contractor":  "professional and scope-focused — what's in the brief, what isn't, what costs extra",
}


def _tone_for(faction: str, role: str) -> str:
    role_lower = (role or "").lower()
    for key, desc in _ROLE_TONE.items():
        if key in role_lower:
            return desc
    if "(Guild)" in (faction or ""):
        return _GUILD_TONE
    return _FACTION_TONE.get(faction or "", "measured and professional — reads the situation before speaking")


# ---------------------------------------------------------------------------
# Faction → what members typically know
# ---------------------------------------------------------------------------

_FACTION_KNOWS: Dict[str, List[str]] = {
    "Iron Fang Consortium": [
        "current black-market pricing and who controls supply in each district",
        "which faction bosses are in debt and to whom",
        "the names of people who have taken Iron Fang contracts and not delivered",
        "which enforcement crews operate in which sectors",
        "how to move product through Warden checkpoints",
    ],
    "Argent Blades": [
        "active contracts on the board and who posted them",
        "which parties have taken similar jobs recently and what happened",
        "the current threat rating of the target area",
        "which fighters in the city take what kind of work",
        "reputation scores and who to trust in the field",
    ],
    "Wardens of Ash": [
        "current patrol routes and checkpoint schedules",
        "outstanding warrants and persons of interest",
        "incident reports from the past month in relevant districts",
        "which factions are expanding and where conflict is building",
        "the official record — and what isn't in the official record",
    ],
    "Serpent Choir": [
        "the terms of any contract passing through their mediation",
        "which disputes are currently unresolved and why",
        "historical precedent for similar agreements",
        "who has standing to make a claim and who doesn't",
        "what either side has already conceded in private",
    ],
    "Obsidian Lotus": [
        "who has been watching whom in the relevant district",
        "which identities are currently compromised",
        "the gap between the official account and the actual one",
        "who requested information about this target or location recently",
        "operational security failures on both sides of this situation",
    ],
    "Glass Sigil": [
        "the archival record of the location, object, or faction in question",
        "prior incidents involving the same parties or places",
        "which documents exist and which ones have been requested recently",
        "the provenance and legal status of anything in their catalogue",
        "what has been officially forgotten and where the record ends",
    ],
    "Patchwork Saints": [
        "who in the district needs help and isn't getting it",
        "which local residents have seen relevant events",
        "the human cost of what is being described as a logistics problem",
        "where the vulnerable people involved can be safely reached",
        "which faction's action caused the most civilian impact",
    ],
    "Adventurers Guild": [
        "the last known party to take a similar job and their outcome",
        "standard rates for this type of contract in current conditions",
        "which skills and equipment matter most for this type of work",
        "area hazards, known creature activity, and local complications",
        "who in the party is known to the Guild and what their record says",
    ],
    "Tower Authority": [
        "the official position and what the official position doesn't cover",
        "which regulations apply and which ones are being ignored",
        "who filed reports about this incident and what those reports said",
        "what Tower Authority jurisdiction covers here — and its edge",
        "which individuals are flagged and what the flagging criteria were",
    ],
    "Wizards Tower": [
        "the theoretical basis for what the party is dealing with",
        "what the Rift or arcane component could become if not handled correctly",
        "who in the Tower has interest in this matter and why",
        "precedent from similar events in the research record",
        "what is being studied quietly that relates to this situation",
    ],
    "Independent": [
        "the local street-level picture that faction members miss",
        "who is reliable in this district and who is performing reliability",
        "what the last three people who touched this situation looked like after",
        "the version of events that never made it into any official account",
        "which direction the pressure is coming from and who's applying it",
    ],
}

_GUILD_KNOWS = [
    "internal contract status and which departments are involved",
    "the guild's official position and the position the director actually holds",
    "which operatives have been assigned and what their current availability is",
    "budget authority — what this job costs and who approved the spend",
    "what the guild is responsible for and what it is carefully not responsible for",
]


def _knows_for(faction: str, role: str, mission_faction: str) -> List[str]:
    base = list(
        _FACTION_KNOWS.get(faction, _FACTION_KNOWS["Independent"])
        if not "(Guild)" in (faction or "")
        else _GUILD_KNOWS
    )
    random.shuffle(base)
    # If this NPC's faction matches the mission faction, they know the inside view
    if faction and mission_faction and faction.lower() == mission_faction.lower():
        base.insert(0, "the internal motivation behind the mission — the version the public brief doesn't include")
    return base[:4]


# ---------------------------------------------------------------------------
# Role → what this person typically withholds
# ---------------------------------------------------------------------------

_ROLE_WITHHOLDS: Dict[str, str] = {
    "enforcer":    "who gave the order and why — they know, they won't say, and they will not be moved on this",
    "archivist":   "the record that was removed and the name of whoever requested the removal",
    "merchant":    "their actual margin and their actual source — the deal is real, the supply chain is not for discussion",
    "informant":   "their other clients and what they've told them — this conversation is not their only one today",
    "healer":      "the name of whoever brought this patient in — they cite confidentiality and mean it",
    "courier":     "the origin and destination in full — they only ever know one leg of the route",
    "scholar":     "the conclusion they haven't published yet — still checking the evidence",
    "priest":      "what their faction leader instructed them to say before this meeting",
    "assassin":    "the client — always; the target in full — sometimes; whether they were here — never confirmed",
    "criminal":    "anything that could be used as evidence — the cost of speaking plainly is too high",
    "officer":     "what the internal investigation found and what was decided not to act on",
    "clerk":       "who told them to process this in the way they did and whether they asked questions",
    "spy":         "everything they're actually here to find out",
    "contractor":  "what happened on the last similar job and why it ended the way it did",
}


def _withholds_for(role: str, secret: str) -> str:
    role_lower = (role or "").lower()
    for key, desc in _ROLE_WITHHOLDS.items():
        if key in role_lower:
            return desc
    # Fall back to a hint from their actual secret if available
    if secret:
        words = [w for w in re.findall(r"[A-Za-z]{5,}", secret) if w.lower() not in ("their", "about", "which", "would", "could", "should", "before", "after", "while")]
        if words:
            return f"the truth behind {words[0].lower()} — they carry this carefully and it shows"
    return "their actual stake in the outcome — they have one and it isn't the obvious one"


# ---------------------------------------------------------------------------
# Mission-context inference
# ---------------------------------------------------------------------------

def _mission_may_know(npc: Dict[str, Any], mission: dict, faction_match: bool) -> List[str]:
    mtype  = (mission.get("mission_type") or mission.get("type") or "").lower()
    title  = mission.get("title", "this situation")
    mfac   = mission.get("faction", "")
    role   = (npc.get("role") or "").lower()
    loc    = npc.get("location") or ""

    pool: List[str] = []

    if faction_match:
        pool.append(f"who authorised the posting and what they told the posting faction internally")
        pool.append(f"the real timeline — when this actually started, not when it was reported")

    if any(w in mtype for w in ("investigation", "find", "missing", "locate")):
        pool += [
            f"a witness in {loc or 'the district'} who hasn't been formally interviewed",
            "which part of the official account is wrong and in which direction it is wrong",
            "who had access to the relevant location before the incident was reported",
        ]
    if any(w in mtype for w in ("heist", "theft", "recover", "retrieve")):
        pool += [
            "which route the object or target moved through and when",
            "who else wanted what was taken and who knew it was there",
            "the current holder's name or operating location",
        ]
    if any(w in mtype for w in ("escort", "protect", "courier", "delivery")):
        pool += [
            "what the principal is not saying about why they need moving",
            "which faction has an active interest in the route being used",
            "the last known complication on this route and who caused it",
        ]
    if any(w in mtype for w in ("assassination", "bounty", "hunt", "kill", "eliminate")):
        pool += [
            "the target's known movements and who they are meeting",
            "who else is looking for the same person and what they want",
            "whether the target knows they are being hunted",
        ]
    if any(w in mtype for w in ("negotiation", "political", "diplomatic")):
        pool += [
            "what Side B actually wants versus what they've said publicly",
            "the pressure point that would shift the balance marker",
            "who stands to lose most if an agreement is reached",
        ]
    if any(w in mtype for w in ("rift", "arcane", "containment", "discovery")):
        pool += [
            "what was in the area before the incident and whether it is still there",
            "who from the Wizards Tower or Tower Authority has already been to the site",
            "what the correct handling procedure is and why it matters",
        ]
    if any(w in mtype for w in ("ambush", "battle", "assault", "defense")):
        pool += [
            "the number and disposition of opposing forces and their known tactics",
            "which approach vector is weakest and why the obvious answer is probably wrong",
            "what the opposition wants beyond the immediate objective",
        ]

    # Generic fallbacks
    pool += [
        f"the street-level version of what happened that never appeared in any report",
        f"a name that connects two parts of this situation that seem unrelated",
        f"what the last party to handle something similar got wrong",
    ]

    random.shuffle(pool)
    return pool[:3]


# ---------------------------------------------------------------------------
# DB lookup
# ---------------------------------------------------------------------------

def _lookup_npc(name: str) -> Optional[Dict[str, Any]]:
    """Look up a named NPC from the DB using real columns."""
    try:
        from src.db_api import raw_query
        sql = (
            "SELECT name, faction, role, location, status, species, "
            "`rank`, motivation, quote, oracle_notes, secret, relationships, data_json "
            "FROM npcs WHERE LOWER(name) = LOWER(%s) LIMIT 1"
        )
        rows = raw_query(sql, (name.strip(),))
        if not rows:
            rows = raw_query(
                sql.replace("= LOWER(%s)", "LIKE LOWER(%s)"),
                (f"{name.strip()}%",),
            )
        if not rows:
            return None
        row = rows[0]
        # General description ("who they are") lives in data_json.appearance —
        # the same description every other surface shows for this NPC.
        description = ""
        dj = row.get("data_json")
        if isinstance(dj, str):
            try:
                dj = json.loads(dj)
            except Exception:
                dj = {}
        if isinstance(dj, dict):
            description = str(dj.get("appearance") or "").strip()
        return {
            "name":         row.get("name", name),
            "faction":      row.get("faction") or "Independent",
            "role":         row.get("role") or "",
            "location":     row.get("location") or "",
            "species":      row.get("species") or "",
            "rank":         row.get("rank") or "",
            "motivation":   row.get("motivation") or "",
            "oracle_notes": row.get("oracle_notes") or "",
            "secret":       row.get("secret") or "",
            "quote":        row.get("quote") or "",
            "relationships":row.get("relationships") or "",
            "appearance":   description,
            "description":  description,
        }
    except Exception:
        return None


def _extract_names_from_scene_npc_lines(npc_lines: List[str]) -> List[str]:
    """Pull the leading name from scene NPC lines like 'Serrik Dhal - contact - wants...'"""
    names = []
    for line in npc_lines:
        # strip bullet markers
        line = re.sub(r"^[-*•]\s*", "", line.strip())
        # name is up to the first dash or comma
        match = re.match(r"^([A-Z][A-Za-z' .-]{1,40}?)(?:\s[-–—]\s|\s*,)", line)
        if match:
            candidate = match.group(1).strip()
            if len(candidate) >= 3 and not candidate.lower().startswith(("local", "bound", "unnamed")):
                names.append(candidate)
    return names


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_e = lambda v: _html.escape(str(v or ""))


def _card_html(npc: Dict[str, Any], mission: dict, mission_faction: str) -> str:
    name     = npc["name"]
    faction  = npc["faction"]
    role     = npc["role"]
    rank     = npc["rank"]
    loc      = npc["location"]
    quote    = npc["quote"]
    motivation = npc["motivation"]
    oracle   = npc["oracle_notes"]
    secret   = npc["secret"]

    faction_match = bool(faction and mission_faction and faction.lower() == mission_faction.lower())
    tone     = _tone_for(faction, role)
    knows    = _knows_for(faction, role, mission_faction)
    may_know = _mission_may_know(npc, mission, faction_match)
    withholds = _withholds_for(role, secret)

    # Voice sample: prefer DB quote, then motivation-derived, then oracle
    voice = quote or ""
    if not voice and motivation:
        # Take first sentence of motivation as a paraphrase hint
        first = re.split(r"[.!?]", motivation)[0].strip()
        if first:
            voice = f"[paraphrase of motivation] {first}."
    if not voice and oracle:
        voice = f"[oracle hint] {oracle.split('.')[0].strip()}."

    # Subtitle line
    subtitle_parts = [p for p in [rank, role, faction] if p]
    subtitle = " · ".join(subtitle_parts)
    if loc:
        subtitle += f" — {loc}"

    # Oracle note (DM only, shown dimmed)
    oracle_row = ""
    if oracle:
        oracle_row = f"""
        <tr>
          <td style="padding:5px 8px;font-weight:600;color:#8a5a1f;white-space:nowrap;vertical-align:top;">Oracle</td>
          <td style="padding:5px 8px;font-size:12px;color:#8a5a1f;font-style:italic;">{_e(oracle)}</td>
        </tr>"""

    # Know rows
    knows_html = "".join(f"<li>{_e(k)}</li>" for k in knows)
    may_html   = "".join(f"<li>{_e(k)}</li>" for k in may_know)

    # Description (who they are) + Motivation (why they care) — surfaced for the
    # DM in the module itself, not just in the NPC's other records.
    description = npc.get("description") or npc.get("appearance") or ""
    desc_row = (
        f'<tr style="border-bottom:1px solid #e8dcc8;">'
        f'<td style="padding:5px 8px;font-weight:600;white-space:nowrap;vertical-align:top;width:120px;">Description</td>'
        f'<td style="padding:5px 8px;">{_e(description)}</td></tr>'
    ) if description else ""
    motiv_row = (
        f'<tr style="border-bottom:1px solid #e8dcc8;background:#fffdf8;">'
        f'<td style="padding:5px 8px;font-weight:600;white-space:nowrap;vertical-align:top;color:#2a5a2a;">Motivation</td>'
        f'<td style="padding:5px 8px;color:#274a27;">{_e(motivation)}</td></tr>'
    ) if motivation else ""

    return f"""
<div style="border:1px solid #c8b89a;border-radius:8px;margin:14px 0;overflow:hidden;font-size:13px;">
  <div style="background:#2a2218;color:#e8dcc8;padding:10px 14px;display:flex;align-items:baseline;gap:10px;">
    <span style="font-weight:700;font-size:15px;">{_e(name)}</span>
    <span style="font-size:12px;opacity:.8;">{_e(subtitle)}</span>
  </div>
  <table style="width:100%;border-collapse:collapse;background:#fdfaf5;">
    {desc_row}{motiv_row}
    <tr style="border-bottom:1px solid #e8dcc8;">
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;vertical-align:top;width:120px;">Knows</td>
      <td style="padding:5px 8px;"><ul style="margin:0;padding-left:18px;">{knows_html}</ul></td>
    </tr>
    <tr style="border-bottom:1px solid #e8dcc8;background:#fffdf8;">
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;vertical-align:top;">May know</td>
      <td style="padding:5px 8px;"><ul style="margin:0;padding-left:18px;">{may_html}</ul></td>
    </tr>
    <tr style="border-bottom:1px solid #e8dcc8;">
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;vertical-align:top;color:#7b1e1e;">Will not say</td>
      <td style="padding:5px 8px;color:#7b1e1e;">{_e(withholds)}</td>
    </tr>
    <tr style="border-bottom:1px solid #e8dcc8;background:#fffdf8;">
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;vertical-align:top;">Tone</td>
      <td style="padding:5px 8px;">{_e(tone)}</td>
    </tr>
    <tr style="border-bottom:1px solid #e8dcc8;">
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;vertical-align:top;">Voice</td>
      <td style="padding:5px 8px;font-style:italic;color:#333;">{_e(voice) if voice else '<span style="color:#aaa;">No quote on file — use motivation above.</span>'}</td>
    </tr>{oracle_row}
  </table>
</div>"""


def _stub_card_html(raw_name: str, mission: dict) -> str:
    """Minimal card for an NPC not found in DB — parsed from scene line."""
    # Try to extract role from the line format "Name - role - wants/knows/hides"
    parts = re.split(r"\s[-–—]\s", raw_name, maxsplit=2)
    name = parts[0].strip() if parts else raw_name.strip()
    role = parts[1].strip() if len(parts) > 1 else ""
    wants_hint = parts[2].strip() if len(parts) > 2 else ""

    mtype = (mission.get("mission_type") or mission.get("type") or "").lower()
    tone  = _tone_for("Independent", role)
    withholds = _withholds_for(role, "")

    may_pool = [
        "the version of events they witnessed directly",
        "a name that links two parts of this situation",
        "what the party hasn't asked yet that matters most",
    ]
    may_html = "".join(f"<li>{_e(k)}</li>" for k in may_pool)

    wants_row = ""
    if wants_hint:
        wants_row = f"""
    <tr style="border-bottom:1px solid #e8dcc8;">
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;">Wants/knows</td>
      <td style="padding:5px 8px;">{_e(wants_hint)}</td>
    </tr>"""

    return f"""
<div style="border:1px solid #c8b89a;border-radius:8px;margin:14px 0;overflow:hidden;font-size:13px;opacity:.92;">
  <div style="background:#3a3228;color:#e8dcc8;padding:10px 14px;display:flex;align-items:baseline;gap:10px;">
    <span style="font-weight:700;font-size:15px;">{_e(name)}</span>
    <span style="font-size:12px;opacity:.8;">{_e(role)} — not in NPC roster</span>
  </div>
  <table style="width:100%;border-collapse:collapse;background:#fdfaf5;">
    {wants_row}
    <tr style="border-bottom:1px solid #e8dcc8;">
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;vertical-align:top;width:120px;">May know</td>
      <td style="padding:5px 8px;"><ul style="margin:0;padding-left:18px;">{may_html}</ul></td>
    </tr>
    <tr style="border-bottom:1px solid #e8dcc8;background:#fffdf8;">
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;color:#7b1e1e;">Will not say</td>
      <td style="padding:5px 8px;color:#7b1e1e;">{_e(withholds)}</td>
    </tr>
    <tr>
      <td style="padding:5px 8px;font-weight:600;white-space:nowrap;">Tone</td>
      <td style="padding:5px 8px;">{_e(tone)}</td>
    </tr>
  </table>
</div>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_npc_cards_html(
    npc_lines: List[str],
    mission: dict,
    *,
    extra_names: Optional[List[str]] = None,
) -> str:
    """
    Given a list of scene NPC lines (format: "Name - role - wants/knows/hides")
    and a mission dict, return an HTML block of NPC knowledge cards.

    extra_names: additional bare names to look up (e.g. contact, mission giver).
    """
    if not npc_lines and not extra_names:
        return ""

    mission_faction = mission.get("faction", "")
    seen: set[str] = set()
    cards: List[str] = []

    # Names extracted from structured lines
    structured_names = _extract_names_from_scene_npc_lines(npc_lines)
    all_names = list(dict.fromkeys(structured_names + (extra_names or [])))

    for name in all_names:
        key = name.lower().strip()
        if key in seen:
            continue
        seen.add(key)

        npc = _lookup_npc(name)
        if npc:
            cards.append(_card_html(npc, mission, mission_faction))
        else:
            # Find the original line for stub card
            original_line = next(
                (ln for ln in npc_lines if name.lower() in ln.lower()),
                name,
            )
            cards.append(_stub_card_html(original_line, mission))

    if not cards:
        return ""

    return (
        '<div style="margin:20px 0;">'
        '<h2 style="font-size:14px;text-transform:uppercase;letter-spacing:.1em;'
        'color:#555;border-bottom:1px solid #ddd;padding-bottom:6px;margin-bottom:4px;">'
        'NPC Knowledge Reference — Call By Name</h2>'
        + "".join(cards)
        + "</div>"
    )


def scene_npc_cards_html(scene: dict, mission: dict) -> str:
    """Convenience wrapper for a single scene dict."""
    return build_npc_cards_html(
        scene.get("npcs", []),
        mission,
    )


def build_module_npc_cards(module_html: str, mission: dict, max_cards: int = 6) -> str:
    """Build NPC knowledge cards (with Description + Motivation) for the mission
    contact plus any roster NPC named in the module HTML. Lets any pipeline's
    module surface who the NPCs are and what they want — not just name them."""
    names: List[str] = []
    contact = (mission.get("contact") or "").strip()
    if contact:
        # Contact strings are often "Name, Location" or "Name - role"; the DB
        # lookup needs just the name part.
        contact = re.split(r"\s[-–—]\s|,", contact)[0].strip()
        if contact:
            names.append(contact)
    try:
        from src.db_api import get_all_npcs
        text_only = re.sub(r"<[^>]+>", " ", module_html or "")
        for r in get_all_npcs() or []:
            nm = str(r.get("name") or "").strip()
            if len(nm) >= 4 and re.search(r"\b" + re.escape(nm) + r"\b", text_only):
                names.append(nm)
    except Exception:
        pass
    names = list(dict.fromkeys(names))[:max_cards]
    if not names:
        return ""
    return build_npc_cards_html([], mission, extra_names=names)
