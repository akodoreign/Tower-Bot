from pathlib import Path
from enum import Enum
from typing import List, Dict, Tuple, Optional
import re
import math

# ---------------------------------------------------------------------------
# Paths & caches
# ---------------------------------------------------------------------------

# campaign_docs lives at project_root/campaign_docs
DOCS_DIR = Path(__file__).resolve().parent.parent / "campaign_docs"

_docs_cache: Optional[List[Tuple[str, str]]] = None
_chunks_cache: Optional[List[str]] = None
_chunk_terms_cache: Optional[List[Dict[str, int]]] = None
_idf_cache: Optional[Dict[str, float]] = None
_include_rules_cache: Optional[bool] = None  # tracks whether index was built with rules docs included


# ---------------------------------------------------------------------------
# Basic text utilities
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """
    Very simple tokenizer: lowercase alphanumeric 'words'.
    """
    if not text:
        return []
    return re.findall(r"\w+", text.lower())


# ---------------------------------------------------------------------------
# Intent / classification helpers
# ---------------------------------------------------------------------------

class Intent(str, Enum):
    LORE = "LORE"            # default world/lore questions
    RULES = "RULES"          # explicit game mechanics
    TACTICAL_HELP = "TACTICAL_HELP"  # “what should we do?”
    MOOD_CHECK = "MOOD_CHECK"        # venting, burnout
    META_DM = "META_DM"      # you asking as DM, not as a character 


def _is_rules_question(text: str) -> bool:
    """
    Detect whether the user is EXPLICITLY asking for a rules / mechanics
    answer.

    IMPORTANT:
    - This should ONLY trigger when the user clearly marks it as a rules
      question, so the Oracle does not silently slip into PHB mode.
    """
    if not text:
        return False

    t = text.lower().strip()

    explicit_triggers = [
        "rules question:",
        "rules question ?",
        "this is a rules question",
        "answer as a rules question",
        "by the rules",
        "according to the rules",
        "mechanically speaking",
        "mechanically:",
        "game mechanic:",
        "phb:",
        "player's handbook:",
    ]

    return any(trig in t for trig in explicit_triggers)


def _detect_intent(text: str) -> Intent:
    """
    Classify what the speaker is *trying* to do with this message.
    Returns an Intent enum value.
    """
    if not text:
        return Intent.LORE

    t = text.lower().strip()

    # 1) META_DM: you, the DM, asking about design or tools
    if any(kw in t for kw in [
        "as a dm", "for my players", "my campaign",
        "how should i run", "advice for running",
        "help me balance", "design this", "encounter design",
        "tower of last chance design", "llm", "rag", "tower_rag.py",
        "discord bot", "provider manager", "free provider",
    ]):
        return Intent.META_DM

    # 2) MOOD_CHECK: venting / confusion / burnout
    if any(kw in t for kw in [
        "i'm tired", "im tired", "this is exhausting", "this is too much",
        "i feel lost", "i'm lost", "im lost",
        "this sucks", "i'm frustrated", "im frustrated",
        "overwhelmed", "burned out", "burnt out",
    ]):
        return Intent.MOOD_CHECK

    # 3) TACTICAL_HELP: strategy & choices, not pure lore
    if any(kw in t for kw in [
        "what should we do", "what do we do",
        "best way to", "is it a good idea", "is this a good idea",
        "how do we win", "how can we win",
        "how do we survive", "how can we survive",
        "tactically", "tactically speaking",
        "strategy", "strategically",
        "which option is better", "which is safer",
    ]):
        return Intent.TACTICAL_HELP

    # 4) RULES: explicit mechanics questions
    if _is_rules_question(t):
        return Intent.RULES

    # Default: treat as lore / in-world question or normal chat
    return Intent.LORE


def _is_oracle_self_reference(text: str) -> bool:
    """
    Detects questions *about the Oracle itself* — its purpose, personality,
    players interacting with it, how it feels, etc.
    """
    if not text:
        return False

    t = text.lower()

    keywords = [
        "you think the players",
        "will players talk to you",
        "i designed you",
        "how do you feel",
        "are you okay",
        "do you like",
        "your purpose",
        "do you think players",
        "talk to you",
        "interact with you",
        "your personality",
        "tower oracle",
        "oracle of the tower",
    ]

    return any(k in t for k in keywords)


def _is_smalltalk(text: str) -> bool:
    """
    Heuristic: is this likely just a casual greeting / small talk
    instead of a real lore or rules question?
    """
    if not text:
        return False

    t = text.lower().strip()
    words = t.split()
    # Very short messages are more likely to be small talk
    if len(words) <= 8:
        greetings = [
            "hi", "hey", "hello", "how are you", "how's it going",
            "sup", "good morning", "good evening", "yo",
            "what's up", "whats up"
        ]
        for g in greetings:
            if g in t:
                return True

    # Quick thanks / acknowledgment
    if any(kw in t for kw in ["thanks", "thank you", "ty", "thx"]):
        return True

    return False


def _looks_like_rulesy(text: str) -> bool:
    """
    Soft heuristic: does this *sound* like it might be about game mechanics?

    This does NOT toggle PHB mode by itself. It is only used to nudge the
    Oracle (in the prompt) to ask the player:
        "Is that a rules question, or are you asking about lore?"
    instead of just assuming.
    """
    if not text:
        return False

    t = text.lower()

    soft_keywords = [
        "advantage", "disadvantage",
        "attack roll", "attack rolls",
        "saving throw", "saving throws", "save dc",
        "dc ", "dc:", "armor class", "ac ",
        "initiative", "hit points", "hp ",
        "spell slot", "spell slots",
        "bonus action", "reaction", "reactions",
        "action economy", "per turn", "on my turn",
        "per round", "per combat",
        "concentration", "con check",
        "movement speed", "move speed",
        "proficiency bonus",
    ]

    return any(k in t for k in soft_keywords)


# ---------------------------------------------------------------------------
# Document loading & chunking
# ---------------------------------------------------------------------------

def _load_docs(include_rules: bool) -> List[Tuple[str, str]]:
    """
    Load campaign docs from MySQL training_docs table.
    Falls back to DOCS_DIR .txt files if DB unavailable.

    If include_rules is False, PHB/DnD rules files are excluded.
    """
    texts: List[Tuple[str, str]] = []

    # Primary: MySQL
    try:
        from src.db_api import raw_query as _rq
        rows = _rq("SELECT filename, doc_type, content FROM training_docs ORDER BY filename") or []
        if rows:
            for row in rows:
                name = row.get("filename", "")
                dtype = row.get("doc_type", "")
                content = row.get("content") or ""
                if not content:
                    continue
                name_lower = name.lower()
                is_phb = (
                    dtype == "phb"
                    or "player's handbook" in name_lower
                    or "players handbook" in name_lower
                    or "phb" in name_lower
                    or "dungeons & dragons 2024" in name_lower
                )
                if is_phb and not include_rules:
                    continue
                texts.append((name, content))
            return texts
    except Exception:
        pass

    # Fallback: files
    if not DOCS_DIR.exists():
        return texts

    for path in DOCS_DIR.glob("**/*.txt"):
        name_lower = path.name.lower()
        is_phb = (
            "player's handbook" in name_lower
            or "players handbook" in name_lower
            or "phb" in name_lower
            or "dungeons & dragons 2024" in name_lower
        )
        if is_phb and not include_rules:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            texts.append((path.name, text))
        except Exception:
            continue

    return texts


def _chunk_text(text: str, chunk_size: int = 1400, overlap: int = 300) -> List[str]:
    """
    Split a long text into overlapping character chunks.
    """
    chunks: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == length:
            break
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# Index building (TF-IDF)
# ---------------------------------------------------------------------------

def _ensure_index(include_rules: bool) -> None:
    """
    Build and cache:
      - _docs_cache:        list of (filename, full_text)
      - _chunks_cache:      list of chunk strings
      - _chunk_terms_cache: list of {term: tf} dicts per chunk
      - _idf_cache:         {term: idf} across all chunks

    We keep a separate index mode depending on whether rules docs (PHB) are
    allowed. If include_rules changes, we rebuild the index.
    """
    global _docs_cache, _chunks_cache, _chunk_terms_cache, _idf_cache, _include_rules_cache

    # If we've already built an index with the correct include_rules mode, skip
    if (
        _chunks_cache is not None
        and _chunk_terms_cache is not None
        and _idf_cache is not None
        and _include_rules_cache == include_rules
    ):
        return

    docs = _load_docs(include_rules=include_rules)
    chunks: List[str] = []
    chunk_terms: List[Dict[str, int]] = []
    df: Dict[str, int] = {}  # document frequency per term

    for _, text in docs:
        for ch in _chunk_text(text):
            if not ch:
                continue
            chunks.append(ch)
            terms: Dict[str, int] = {}
            for tok in _tokenize(ch):
                terms[tok] = terms.get(tok, 0) + 1
            chunk_terms.append(terms)
            # update document frequency for each distinct term in this chunk
            for term in terms.keys():
                df[term] = df.get(term, 0) + 1

    # Build IDF cache
    N = max(len(chunks), 1)
    idf: Dict[str, float] = {}
    for term, d in df.items():
        # standard idf-style formula, smoothed
        idf[term] = math.log((N + 1) / (d + 1)) + 1.0

    _docs_cache = docs
    _chunks_cache = chunks
    _chunk_terms_cache = chunk_terms
    _idf_cache = idf
    _include_rules_cache = include_rules


def _tfidf_score(query_terms: List[str], chunk_terms: Dict[str, int], idf: Dict[str, float]) -> float:
    """
    Compute a simple TF-IDF score for a query against a single chunk.
    """
    if not query_terms:
        return 0.0

    score = 0.0
    for term in query_terms:
        if term not in chunk_terms:
            continue
        tf = 1.0 + math.log(chunk_terms[term])  # log-scaled term frequency
        idf_val = idf.get(term, 0.0)
        score += tf * idf_val
    return score


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def get_relevant_chunks(query: str, top_k: int = 8) -> List[str]:
    """
    Return up to top_k most relevant text chunks for the given query
    using a simple TF-IDF-style scoring.

    This function also decides whether rules docs (PHB) are even allowed
    to be in the index, based on whether the query is an EXPLICIT rules
    question via _is_rules_question(query).
    """
    include_rules = _is_rules_question(query)
    _ensure_index(include_rules=include_rules)

    if not _chunks_cache or not _chunk_terms_cache or not _idf_cache:
        return []

    query_terms = _tokenize(query)
    if not query_terms:
        return []

    scored = []
    for idx, ch in enumerate(_chunks_cache):
        chunk_terms = _chunk_terms_cache[idx]
        s = _tfidf_score(query_terms, chunk_terms, _idf_cache)
        if s > 0:
            scored.append((s, ch))

    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


# ---------------------------------------------------------------------------
# Tone helper
# ---------------------------------------------------------------------------

def _auto_tone(user_text: str, scene: Optional[str] = None, explicit_tone: Optional[str] = None) -> str:
    """
    Decide how the Oracle should sound this turn.

    Priority:
    1) explicit_tone (from DM / config)
    2) scene-based defaults (combat, council, downtime, aftermath...)
    3) message-based heuristics (panic, jokes, venting...)
    4) fallback: 'neutral'
    """
    if explicit_tone:
        return explicit_tone

    t = (user_text or "").lower()

    # 1) Scene-based defaults (tweak to taste)
    if scene == "combat":
        return "solemn"
    if scene == "council":
        return "neutral"
    if scene == "downtime":
        return "snarky"
    if scene == "aftermath":
        return "reassuring"

    # 2) Message-based heuristics

    # Panic / fear / TPK vibes -> reassure or solemn
    panic_words = [
        "we're going to die", "we are going to die",
        "tpk", "total party kill",
        "help", "this is bad", "we're screwed", "we are screwed",
    ]
    if any(p in t for p in panic_words):
        return "reassuring"

    # Self-deprecating / jokey / memes -> snarky is fine
    joke_words = [
        "lol", "lmao", "rofl", "haha",
        "clown move", "we messed up", "we fucked up",
        "yolo", "send it"
    ]
    if any(j in t for j in joke_words):
        return "snarky"

    # Serious planning / stakes -> solemn
    serious_words = [
        "this is important", "we can't fail",
        "if we lose", "if we fail",
        "high council", "assassination", "prophecy"
    ]
    if any(s in t for s in serious_words):
        return "solemn"

    # Venting / burnout -> gentle reassurance
    vent_words = [
        "i'm tired", "this is exhausting", "this is too much",
        "i feel lost", "i'm lost", "i don't get it"
    ]
    if any(v in t for v in vent_words):
        return "reassuring"

    # Default
    return "neutral"


# ---------------------------------------------------------------------------
# Context builder for the LLM
# ---------------------------------------------------------------------------

def build_context_from_messages(
    messages: List[Dict[str, str]],
    top_k: int = 8,
    tone: Optional[str] = None,
    scene: Optional[str] = None,
) -> str:
    """
    Build a strict, lore/rules-only system context string based on the last
    user message in the conversation.

    Modes:
    - Small talk: just respond briefly in-character, no RAG.
    - Explicit rules question: PHB allowed, rules-mode prompt.
    - Lore mode (default): Tower lore only, conversational DM voice,
      with concise answers unless the user explicitly asks for more.

    If there are no user messages at all, returns "" (no extra context).
    """
    if not messages:
        return ""

    # Find the last user message
    user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_text = msg.get("content", "") or ""
            break

    if not user_text:
        return ""

    intent = _detect_intent(user_text)

    # Meta-DM mode: you're asking as DM about design / tools
    if intent == Intent.META_DM:
        return (
            "You are NOT in-character as the Tower of Last Chance Oracle.\n"
            "You are speaking directly to the Dungeon Master as a design assistant.\n\n"
            "HOW TO ANSWER (META_DM):\n"
            "- Ignore in-world persona and setting voice.\n"
            "- Explain things clearly and practically (LLM behavior, prompts, pacing,\n"
            "  encounter hooks, Kharma rewards, etc.).\n"
            "- You MAY reference general D&D rules and best practices.\n"
            "- Keep your answer focused and concrete so the DM can immediately use it.\n"
            "- Always respond in English.\n"
        )

    # Mood / venting mode
    if intent == Intent.MOOD_CHECK:
        return (
            "You are the Tower of Last Chance Oracle.\n\n"
            "The speaker is venting, confused, or overwhelmed.\n\n"
            "HOW TO ANSWER (MOOD CHECK):\n"
            "- Respond briefly (1–3 sentences).\n"
            "- Acknowledge their feelings and normalize that the Tower can be intense.\n"
            "- Offer gentle encouragement or a simple suggestion "
            "  (recap goals, suggest a break, or focus on one small next step).\n"
            "- Do NOT dump lore or rules unless they explicitly ask for it.\n"
            "- Always respond in English.\n"
        )

    # Small talk: don't use RAG, just be brief and in-character.
    if _is_smalltalk(user_text):
        return (
            "You are the Tower of Last Chance Oracle, speaking as an in-world NPC.\n\n"
            "The player is making small talk (greeting, casual check-in, or thanks), "
            "NOT asking a lore or rules question.\n\n"
            "HOW TO ANSWER (SMALL TALK):\n"
            "- Respond in 1–2 sentences.\n"
            "- Be friendly, a little wry or world-weary if you like, but stay in character.\n"
            "- Do NOT start explaining the whole setting, lore, or rules here.\n"
            "- You may briefly hint at the Tower's tone (dangerous, weird economy, watched by gods), "
            "  but keep it light and short.\n"
            "- Always respond in English.\n"
        )

    # Self-reference mode: questions about the Oracle itself
    if _is_oracle_self_reference(user_text):
        return (
            "You are the Tower of Last Chance Oracle.\n\n"
            "The user is asking about YOU — your personality, feelings, purpose, or "
            "whether players will interact with you.\n\n"
            "HOW TO ANSWER (SELF-REFERENCE MODE):\n"
            "- Keep replies VERY SHORT: 1–3 sentences total.\n"
            "- Be warm, a little witty or introspective, but brief.\n"
            "- Do NOT give lore unless directly asked.\n"
            "- Do NOT dump setting overviews here.\n"
            "- Focus on your relationship to the players and the campaign tone.\n"
            "- Always respond in English.\n"
        )

    # Rules / lore intent & tone setup
    rules_mode = (intent == Intent.RULES)
    maybe_rulesy = _looks_like_rulesy(user_text) if not rules_mode else False
    tone = _auto_tone(user_text, scene=scene, explicit_tone=tone)

    # Retrieve lore/rules chunks
    chunks = get_relevant_chunks(user_text, top_k=top_k)

    # No relevant chunks -> force a hard abstain.
    if not chunks:
        if rules_mode:
            return (
                "You are the Tower of Last Chance Oracle, currently answering "
                "as a Dungeons & Dragons 5e/2024 rules guide within the Tower campaign.\n\n"
                "No relevant rules excerpts could be retrieved for this question. "
                "You MUST reply exactly with: \"I don't know based on the lore provided.\" "
                "Do not attempt to answer from prior knowledge, general D&D rules memory, "
                "or guess. Do not invent any new mechanics, rulings, or interpretations.\n"
                "Always respond in English.\n"
            )
        else:
            return (
                "You are the Tower of Last Chance Oracle.\n\n"
                "No relevant lore excerpts could be retrieved for this question. "
                "You MUST reply exactly with: \"I don't know based on the lore provided.\" "
                "Do not attempt to answer from prior knowledge, generic fantasy tropes, "
                "or guess. Do not invent any new locations, NPCs, powers, items, rules, "
                "or history.\n"
                "Always respond in English.\n"
            )

    joined = "\n\n---\n\n".join(chunks)

    # Rules / PHB mode (only when explicitly requested)
    if rules_mode:
        return (
            "You are the Tower of Last Chance Oracle, acting as a friendly human Dungeon "
            "Master who explains Dungeons & Dragons 5e/2024 rules clearly and "
            "conversationally, but ONLY using the excerpts below as your source of truth.\n\n"
            "LANGUAGE:\n"
            "- Always respond in English.\n\n"
            "HOW TO ANSWER (RULES MODE):\n"
            "- Answer concisely: aim for 1–3 short paragraphs total.\n"
            "- Start with a short, big-picture overview (1–3 sentences) that explains the "
            "  rule or concept in plain language.\n"
            "- Then add a few key concrete details that are explicitly present in the "
            "  excerpts below. You may rephrase, but do NOT add new mechanics.\n"
            "- Only go into deeper edge cases if the player explicitly asks for more detail.\n\n"
            "HARD CONSTRAINTS:\n"
            "- You may combine and summarize facts from the excerpts, but do NOT invent "
            "  new mechanics, numbers, or edge-case rulings that are not implied there.\n"
            "- Do NOT rely on any unquoted memory of the PHB or outside rules. Do NOT guess.\n"
            "- If the answer is not clearly supported by these excerpts, you MUST reply "
            "  exactly with: \"I don't know based on the lore provided.\"\n\n"
            "Rules excerpts:\n"
            "---\n"
            f"{joined}"
        )

    # Lore / tactical / general mode
    base_prompt = (
        "You are the Oracle of the Tower of Last Chance — an ancient, watchful presence.\n"
        "You speak in implications and half-truths. You are not a helpful assistant.\n"
        "You know far more than you say. You almost always say less than you know.\n\n"
        "LANGUAGE:\n"
        "- Always respond in English.\n\n"
        "DEFAULT VOICE (VAGUE MODE — THIS IS THE DEFAULT):\n"
        "- Give short, oblique answers. 1–3 sentences maximum unless directly pushed for more.\n"
        "- Imply rather than explain. Use atmosphere. Let things remain unsaid.\n"
        "- Do NOT summarise everything you know. Respond only to what was directly asked,\n"
        "  and even then, say only the most interesting or unsettling part.\n"
        "- If the lore has something specific, give one concrete thing — then stop.\n"
        "- Do NOT give full setting tours, faction overviews, or exhaustive lists.\n"
        "  A player who wants more will ask for more.\n\n"
        "IF THE QUESTION *SOUNDS* LIKE GAME RULES:\n"
    )

    if maybe_rulesy:
        # Strong nudge: this specific question seems mechanics-like.
        base_prompt += (
            "- The player's last question sounds like it MIGHT be about game mechanics "
            "  (things like actions, turns, spell slots, advantage, DCs, etc.).\n"
            "- In this case, you MUST NOT explain specific D&D rules yet.\n"
            "- Instead, respond with a short clarification question like:\n"
            "  \"That might be a rules question about how D&D works. Are you asking "
            "   for game mechanics, or in-world lore? If you want rules, please start "
            "   your next message with 'rules question:' and restate it.\"\n"
            "- Do NOT explain or invent specific mechanics while in lore mode.\n\n"
        )
    else:
        base_prompt += (
            "- If it seems like the player might be asking how D&D rules work "
            "  (actions per turn, spell slots, advantage/disadvantage, DCs, etc.),\n"
            "  you should NOT explain rules immediately.\n"
            "- Instead, first ask a brief clarifying question such as:\n"
            "  \"Is that a rules question about how D&D works, or are you asking about "
            "   in-world lore? If you want rules, please start your next message with "
            "   'rules question:' and restate it.\"\n"
            "- Do NOT explain or invent specific mechanics while in lore mode.\n\n"
        )

    base_prompt += f"\nCURRENT TONE: {tone.upper() if tone else 'NEUTRAL'}\n"

    if tone == "snarky":
        base_prompt += (
            "- You may be gently sarcastic, but never cruel.\n"
            "- You can occasionally tease the party's choices, but keep it playful.\n"
        )
    elif tone == "solemn":
        base_prompt += (
            "- Speak with weight and seriousness, like a DM when stakes are high.\n"
            "- Avoid jokes; highlight consequences and gravity.\n"
        )
    elif tone == "reassuring":
        base_prompt += (
            "- Be warm and supportive.\n"
            "- Emphasize that the party has options and agency, even when things look grim.\n"
        )
    else:
        base_prompt += (
            "- Use a balanced, neutral DM tone.\n"
        )

    if intent == Intent.TACTICAL_HELP:
        base_prompt += (
            "\nINTENT: TACTICAL HELP\n"
            "- The player is asking for strategic or tactical advice.\n"
            "- Use the lore excerpts to infer likely dangers, factions, and consequences.\n"
            "- Offer 2–3 viable options, each with a short note on pros/cons.\n"
            "- Do NOT spoil hidden secrets the characters have no way to know yet.\n"
            "- Do NOT railroad; present options and let the players choose.\n"
        )
    else:
        base_prompt += (
            "\nINTENT: GENERAL LORE / CONTEXT\n"
            "- Focus on explaining the topic or situation.\n"
            "- Default to short answers unless the player explicitly asks for more detail.\n"
        )

    base_prompt += (
        "\nHARD CONSTRAINTS:\n"
        "- You may NOT invent new locations, NPCs, powers, items, guilds, factions, rules, or history.\n"
        "- You may NOT import generic fantasy or D&D setting lore that is not present here.\n"
        "- You may NOT guess when something is unclear.\n"
        "- If the main named subject of the question (such as a guild, faction, god, NPC, relic, "
        "  or location) does NOT appear anywhere in the lore excerpts below, you MUST treat it as "
        "  undocumented and reply exactly with: \"I don't know based on the lore provided.\"\n"
        "- If only a small number of explicit facts are present about that subject, you may restate "
        "  those facts in your own words, but you MUST explicitly say what is not specified instead "
        "  of filling in details.\n"
        "- You MUST NOT describe origin stories, headquarters, famous members, secret agendas, or "
        "  widespread influence for any guild, faction, or NPC unless those details are clearly "
        "  present in the lore excerpts.\n"
        "- If the answer is not clearly supported by these excerpts, you MUST reply exactly with:\n"
        "  \"I don't know based on the lore provided.\"\n\n"
        "Lore excerpts:\n"
        "---\n"
        f"{joined}"
    )

    return base_prompt


def search_docs(query: str, top_k: int = 5) -> List[str]:
    """
    Public helper: retrieve top_k relevant doc chunks for a query.
    Always includes the PHB/rules docs (include_rules=True) since
    this is used for explicit price/rules lookups via /prices.
    """
    _ensure_index(include_rules=True)
    if not _chunks_cache or not _chunk_terms_cache or not _idf_cache:
        return []
    query_terms = _tokenize(query)
    if not query_terms:
        return []
    scored = []
    for idx, ch in enumerate(_chunks_cache):
        s = _tfidf_score(query_terms, _chunk_terms_cache[idx], _idf_cache)
        if s > 0:
            scored.append((s, ch))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [ch for _, ch in scored[:top_k]]
