"""
Webpage/app.py — TowerBot Dashboard Flask backend.

Serves the mission generator dashboard and provides REST API endpoints
that connect the HTML UI to the bot's data (missions, NPCs, gazetteer, etc.).

Run:
    cd Webpage
    python app.py
    # → http://localhost:5000
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[mKGHFJABCDnsr]')

# Allow imports from the project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask, jsonify, render_template, request, send_from_directory
try:
    from flask_cors import CORS
    _cors_available = True
except ImportError:
    _cors_available = False

app = Flask(
    __name__,
    template_folder="MissionGenerator-Designs",
    static_folder="MissionGenerator-Designs",
)
if _cors_available:
    CORS(app)

# Add CORS headers manually if flask_cors not installed
@app.after_request
def _add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response

DOCS_DIR = PROJECT_ROOT / "campaign_docs"


def _json_obj(value, default=None):
    """Return a dict/list from a MySQL JSON column without leaking parse errors."""
    if default is None:
        default = {}
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default
    return default


def _pick_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _mission_generation_context_block(limit: int = 6) -> str:
    """Build a compact live-world context block for dashboard mission seeds."""
    try:
        from src.db_api import get_global_state, raw_query
    except Exception as exc:
        logger.warning(f"mission context unavailable: {exc}")
        return "Live world context unavailable; use the submitted brief and location context."

    def _rows(query: str, params: tuple = ()) -> list[dict]:
        try:
            return raw_query(query, params) or []
        except Exception as exc:
            logger.warning(f"mission context query failed: {exc}")
            return []

    def _trim(text: object, max_len: int = 240) -> str:
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        return clean[:max_len].rstrip()

    news = [
        _trim(row.get("facts") or row.get("bulletin_text"))
        for row in _rows(
            "SELECT facts, bulletin_text FROM news_memory ORDER BY created_at DESC, id DESC LIMIT %s",
            (limit,),
        )
    ]
    outcomes = []
    for row in _rows(
        "SELECT mission_title, result, key_decisions, loose_threads, notable_moments "
        "FROM mission_outcomes ORDER BY completed_at DESC, id DESC LIMIT %s",
        (limit,),
    ):
        bits = [
            row.get("mission_title"),
            row.get("result"),
            row.get("key_decisions"),
            row.get("loose_threads"),
            row.get("notable_moments"),
        ]
        outcomes.append(_trim(" | ".join(str(b) for b in bits if b)))

    recent_titles = [
        _trim(row.get("title"), 90)
        for row in _rows("SELECT title FROM missions ORDER BY id DESC LIMIT 18")
        if row.get("title")
    ]

    council_items = []
    try:
        rulings = get_global_state("council_rulings") or []
        if isinstance(rulings, str):
            rulings = json.loads(rulings)
        if isinstance(rulings, list):
            for item in rulings[-limit:]:
                if isinstance(item, dict):
                    council_items.append(_trim(" | ".join(str(item.get(k, "")) for k in ("topic", "ruling", "outcome") if item.get(k))))
                else:
                    council_items.append(_trim(item))
    except Exception as exc:
        logger.warning(f"council context unavailable: {exc}")

    lines = ["LIVE WORLD CONTEXT -- use this as cause-and-effect fuel, not decoration:"]
    if news:
        lines.append("Recent news:")
        lines.extend(f"- {n}" for n in news if n)
    if outcomes:
        lines.append("Previous mission fallout:")
        lines.extend(f"- {o}" for o in outcomes if o)
    if council_items:
        lines.append("Council decisions / political pressure:")
        lines.extend(f"- {c}" for c in council_items if c)
    if recent_titles:
        lines.append("Recent mission titles to avoid echoing:")
        lines.extend(f"- {t}" for t in recent_titles if t)
    lines.append("Butterfly-effect rule: the new public job must visibly answer one of these items through a named person, place, faction, debt, rumor, missing object, or retaliation.")
    return "\n".join(lines)


_TIER_TO_DIFF = {
    "local": 2, "patrol": 2, "escort": 3, "standard": 4,
    "investigation": 5, "inter-guild": 5,
    "major": 6, "rift": 7, "high-stakes": 7,
    "tower": 8, "dungeon": 8, "divine": 9, "epic": 10,
}

def _mission_difficulty(row: dict, mission_json: dict) -> object:
    """Prefer the explicit 1-10 mission difficulty, falling back to legacy labels then tier."""
    for value in (
        row.get("difficulty"),
        mission_json.get("difficulty_rating"),
        mission_json.get("difficulty"),
    ):
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    # Fall back to tier when difficulty is absent
    tier = (row.get("tier") or mission_json.get("tier") or "").strip().lower()
    return _TIER_TO_DIFF.get(tier, "") or ""


def _short_text(value: object, limit: int = 320) -> str:
    text = _pick_text(value)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rsplit(" ", 1)[0].rstrip() + "…"


def _slug(value: object) -> str:
    return re.sub(r"[^a-z0-9_]", "_", _pick_text(value).lower().strip()).strip("_")[:80]


def _path_within(path: Path, root: Path) -> bool:
    """Return true only when path resolves inside root."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helper: safe DB import
# ---------------------------------------------------------------------------

def _db_ok() -> bool:
    try:
        from src.db_api import raw_query
        raw_query("SELECT 1")
        return True
    except Exception:
        return False


def _ollama_ok() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(
            os.getenv("OLLAMA_URL", "http://localhost:11434").split("/api/")[0] + "/api/tags",
            timeout=2,
        ) as r:
            return r.status == 200
    except Exception:
        return False


def _ollama_detail() -> dict:
    """Return {ok, busy, reason, model} for richer status display."""
    try:
        import urllib.request, json as _json
        base = os.getenv("OLLAMA_URL", "http://localhost:11434").split("/api/")[0]
        with urllib.request.urlopen(base + "/api/ps", timeout=2) as r:
            ps = _json.loads(r.read())
        models_running = ps.get("models", [])
        busy = len(models_running) > 0
        # Check bot-level busy flag from DB
        try:
            from src.db_api import raw_query
            row = raw_query("SELECT state_value FROM global_state WHERE state_key='ollama_busy_reason'")
            bot_reason = row[0]["state_value"] if row else ""
        except Exception:
            bot_reason = ""
        return {
            "ok": True,
            "busy": busy or bool(bot_reason),
            "reason": bot_reason or (models_running[0].get("name", "") if models_running else ""),
            "model": models_running[0].get("name", "") if models_running else os.getenv("KIMI_MODEL", ""),
        }
    except Exception:
        return {"ok": False, "busy": False, "reason": "offline", "model": ""}


def _a1111_detail() -> dict:
    """Return {ok, model, busy} for A1111."""
    try:
        import urllib.request, json as _json
        base = "http://127.0.0.1:7860"
        # Current model
        with urllib.request.urlopen(base + "/sdapi/v1/options", timeout=2) as r:
            opts = _json.loads(r.read())
        model = opts.get("sd_model_checkpoint", "").split("/")[-1].split("\\")[-1]
        model = model[:30] if model else "unknown"
        # Busy state
        try:
            with urllib.request.urlopen(base + "/sdapi/v1/progress", timeout=2) as r:
                prog = _json.loads(r.read())
            busy = prog.get("state", {}).get("job_count", 0) > 0
            progress = prog.get("progress", 0.0)
        except Exception:
            busy = False
            progress = 0.0
        return {"ok": True, "model": model, "busy": busy, "progress": progress}
    except Exception:
        return {"ok": False, "model": "", "busy": False, "progress": 0.0}


def _discord_ok() -> dict:
    """Check Discord bot liveness via its global_state heartbeat (written every minute)."""
    try:
        from src.db_api import get_global_state
        from datetime import datetime, timezone
        status = get_global_state("discord_status") or {}
        if not status.get("ok"):
            return {"ok": False, "label": "unreachable"}
        updated_at = status.get("updated_at", "")
        if updated_at:
            try:
                age = (datetime.utcnow() - datetime.fromisoformat(updated_at)).total_seconds()
                if age > 180:  # stale if bot hasn't ticked in 3 minutes
                    return {"ok": False, "label": "stale"}
            except Exception:
                pass
        return {"ok": True, "label": status.get("label", "connected")}
    except Exception:
        return {"ok": False, "label": "unreachable"}


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("MissionGenerator-Designs", "Web Dashboard.html")


@app.route("/print")
def print_view():
    return send_from_directory("MissionGenerator-Designs", "Mission Module Print.html")


# ---------------------------------------------------------------------------
# /api/status — backend health indicators
# ---------------------------------------------------------------------------

@app.route("/api/status")
def api_status():
    ollama  = _ollama_detail()
    a1111   = _a1111_detail()
    discord = _discord_ok()
    db_up   = _db_ok()
    try:
        from src.resource_cop import active_pipelines_sync
        pipelines = active_pipelines_sync()
    except Exception:
        pipelines = []

    mimir_ok = False
    try:
        from src.mimir_client import get_mimir
        mimir_ok = get_mimir().available
    except Exception:
        pass

    return jsonify({
        "ollama":  {"ok": ollama["ok"], "busy": ollama["busy"], "reason": ollama["reason"], "model": ollama["model"]},
        "a1111":   {"ok": a1111["ok"], "model": a1111["model"], "busy": a1111["busy"], "progress": a1111["progress"]},
        "discord": {"ok": discord["ok"], "label": discord["label"]},
        "db":      {"ok": db_up},
        "mimir":   {"ok": mimir_ok},
        "pipelines": {"active": pipelines, "count": len(pipelines)},
    })


# ---------------------------------------------------------------------------
# /api/missions — active missions
# ---------------------------------------------------------------------------

def _serialize_mission(r: dict) -> dict:
    """Flatten a missions row into a clean JSON-safe dict for the web dashboard."""
    mj = r.get("mission_json") or {}
    if isinstance(mj, str):
        try: mj = json.loads(mj)
        except: mj = {}

    title = r.get("title") or mj.get("title", "Unknown Contract")

    # mission_type: DB row > mission_json.type > mission_json.mission_type > parse from title
    mission_type = (
        mj.get("type") or
        mj.get("mission_type") or
        r.get("mission_type", "")
    )
    if not mission_type and ":" in title:
        prefix = title.split(":", 1)[0].strip().split()
        if prefix:
            mission_type = prefix[-1].lower()

    # reward: mission_json.reward (string) takes priority over reward_ec (int)
    reward_str = mj.get("reward", "")
    reward_ec  = r.get("reward_ec", 0)
    if not reward_str and reward_ec:
        reward_str = f"{reward_ec:,} EC"

    # body text: mission_json.story_text (clean) then mission_json.body then description
    body = (
        mj.get("story_text") or
        mj.get("body") or
        mj.get("brief") or
        r.get("description") or
        mj.get("description", "")
    )

    # contact
    contact = mj.get("contact", "")

    # opposing faction
    opposing = mj.get("opposing_faction", "")

    return {
        "id":               r.get("id"),
        "title":            title,
        "faction":          r.get("faction") or mj.get("faction", ""),
        "mission_type":     mission_type,
        "type":             mission_type,          # alias for JS that checks m.type
        "tier":             r.get("tier") or mj.get("tier", ""),
        "difficulty":       _mission_difficulty(r, mj),
        "status":           r.get("status", "active"),
        "reward":           reward_str,
        "reward_ec":        reward_ec,
        "npc_giver":        r.get("npc_giver") or mj.get("npc_giver", ""),
        "claimed_by":       r.get("claimed_by") or mj.get("player_claimer", ""),
        "opposing_faction": opposing,
        "contact":          contact,
        "body":             body,
        "created_at":       str(r.get("created_at", "")),
        "posted_at":        str(r.get("posted_at") or mj.get("posted_at", "")),
        "expires_at":       str(r.get("expires_at") or mj.get("expires_at", "")),
        "message_id":       r.get("message_id") or mj.get("message_id"),
        "personal_for":     mj.get("personal_for", ""),
        "module_slug":      r.get("module_slug") or "",
        # Debrief outcome fields — joined from mission_outcomes table by title match
        "outcome":          r.get("_outcome") or {},
    }


@app.route("/api/missions")
def api_missions():
    tab    = request.args.get("tab", "all")       # all | active | claimed | failed | drafts
    search = request.args.get("search", "").strip()
    types  = request.args.get("types", "").strip() # comma-separated mission_type values
    limit  = min(int(request.args.get("limit", 100)), 500)

    tab_wheres = {
        "all":       "",
        "active":    "WHERE status = 'active' AND message_id IS NOT NULL",
        "claimed":   "WHERE status = 'claimed'",
        "completed": "WHERE status = 'completed'",
        "failed":    "WHERE status IN ('failed','expired')",
        "drafts":    "WHERE JSON_EXTRACT(mission_json, '$.source') = 'dashboard'",
    }
    where  = tab_wheres.get(tab, "")
    params: list = []

    try:
        from src.db_api import raw_query

        if types:
            type_list = [t.strip().lower() for t in types.split(",") if t.strip()]
            ph = ",".join(["%s"] * len(type_list))
            joiner = "AND" if where else "WHERE"
            # Check both $.type and $.mission_type so dashboard-created and bot-created missions match
            where += (
                f" {joiner} (LOWER(JSON_UNQUOTE(JSON_EXTRACT(mission_json,'$.mission_type'))) IN ({ph})"
                f" OR LOWER(JSON_UNQUOTE(JSON_EXTRACT(mission_json,'$.type'))) IN ({ph}))"
            )
            params.extend(type_list * 2)

        if search:
            joiner = "AND" if where else "WHERE"
            where += f" {joiner} (title LIKE %s OR faction LIKE %s)"
            params.extend([f"%{search}%", f"%{search}%"])

        rows = raw_query(
            f"SELECT * FROM missions {where} ORDER BY created_at DESC LIMIT %s",
            (*params, limit),
        ) or []
        # For completed/failed missions, join debrief outcomes — prefer mission_id over title
        if rows and tab in ("completed", "failed", "all"):
            ids = [r["id"] for r in rows if r.get("id")]
            titles = [r.get("title", "") for r in rows if r.get("title")]
            outcome_map: dict = {}  # keyed by mission_id (int) or title (str)
            if ids:
                id_ph = ",".join(["%s"] * len(ids))
                id_rows = raw_query(
                    f"SELECT mission_id, mission_title, result, completed_by, completed_at, "
                    f"npcs_killed, key_decisions, location_changes, loose_threads, notable_moments "
                    f"FROM mission_outcomes WHERE mission_id IN ({id_ph}) "
                    f"ORDER BY created_at DESC",
                    tuple(ids),
                ) or []
                for o in id_rows:
                    outcome_map[o["mission_id"]] = o
            if titles:
                covered_titles = {o["mission_title"] for o in outcome_map.values()}
                remaining = [t for t in titles if t not in covered_titles]
                if remaining:
                    t_ph = ",".join(["%s"] * len(remaining))
                    t_rows = raw_query(
                        f"SELECT mission_title, result, completed_by, completed_at, "
                        f"npcs_killed, key_decisions, location_changes, loose_threads, notable_moments "
                        f"FROM mission_outcomes WHERE mission_id IS NULL AND mission_title IN ({t_ph}) "
                        f"ORDER BY created_at DESC",
                        tuple(remaining),
                    ) or []
                    for o in t_rows:
                        outcome_map[o["mission_title"]] = o
            for r in rows:
                r["_outcome"] = outcome_map.get(r["id"]) or outcome_map.get(r.get("title", ""), {})
        results = [_serialize_mission(r) for r in rows]
        return jsonify({"missions": results, "count": len(results)})
    except Exception as e:
        return jsonify({"missions": [], "count": 0, "error": str(e)})


@app.route("/api/missions/<int:mission_id>")
def api_mission_detail(mission_id: int):
    try:
        from src.db_api import raw_query
        rows = raw_query("SELECT * FROM missions WHERE id = %s LIMIT 1", (mission_id,))
        if not rows:
            return jsonify({"error": "not found"}), 404
        row = rows[0]
        title = row.get("title", "")
        if title or mission_id:
            outcome_rows = raw_query(
                "SELECT result, completed_by, completed_at, npcs_killed, key_decisions, "
                "location_changes, loose_threads, notable_moments "
                "FROM mission_outcomes WHERE mission_id = %s OR (mission_id IS NULL AND mission_title = %s) "
                "ORDER BY (mission_id IS NOT NULL) DESC, created_at DESC LIMIT 1",
                (mission_id, title),
            ) or []
            row["_outcome"] = outcome_rows[0] if outcome_rows else {}
        return jsonify({"mission": _serialize_mission(row), "ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/claim-mission", methods=["POST"])
def api_claim_mission():
    """Queue a dashboard claim for the bot to process with its live Discord client."""
    data       = request.get_json(force=True) or {}
    if _is_external() and not _pin_ok(data):
        return jsonify({"error": "PIN required.", "pin_required": True}), 403

    mission_id = data.get("mission_id")
    if not mission_id:
        return jsonify({"error": "mission_id required"}), 400

    try:
        from src.db_api import enqueue_dashboard_claim_job, raw_query, set_global_state

        rows = raw_query("SELECT id, title, status, message_id FROM missions WHERE id = %s", (mission_id,))
        if not rows:
            return jsonify({"error": "Mission not found"}), 404

        current_status = rows[0].get("status", "active")
        if current_status in ("claimed", "completed", "failed", "expired"):
            return jsonify({"error": f"Mission already {current_status}"}), 400

        if not rows[0].get("message_id"):
            return jsonify({"error": "Mission has no Discord board message to claim"}), 400

        # Queue the claim for the bot process. The bot owns the Discord client,
        # so it must perform the claim notice, board-message deletion, DM buttons,
        # and module-generation handoff. The dashboard must not fake a bot
        # reaction or mark the row claimed before that path runs.
        job_id = enqueue_dashboard_claim_job(
            int(mission_id),
            claimer="DM Dashboard",
            title=rows[0].get("title", "Unknown Mission"),
        )
        set_global_state(f"dashboard_claim_status:{int(mission_id)}", {
            "state": "queued",
            "mission_id": int(mission_id),
            "job_id": job_id,
            "title": rows[0].get("title", "Unknown Mission"),
            "message": "Queued for Discord bot handoff",
            "updated_at": datetime.utcnow().isoformat(),
        })

        return jsonify({"ok": True, "queued": True, "job_id": job_id, "handoff": "discord_bot"})

    except Exception as e:
        logger.error(f"api_claim_mission error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/claim-mission-status/<int:mission_id>")
def api_claim_mission_status(mission_id: int):
    """Return dashboard-visible claim/module generation progress for one mission."""
    if _is_external() and not _pin_ok(request.args):
        return jsonify({"error": "PIN required.", "pin_required": True}), 403

    try:
        from src.db_api import (
            get_latest_dashboard_claim_job,
            get_latest_module_generation_job,
            get_global_state,
            raw_query,
        )

        status = get_global_state(f"dashboard_claim_status:{mission_id}") or {}
        claim_job = get_latest_dashboard_claim_job(mission_id)
        module_job = get_latest_module_generation_job(mission_id)
        if claim_job:
            status.setdefault("job_id", claim_job.get("id"))
            status["claim_job_status"] = claim_job.get("status")
            if claim_job.get("status") == "failed" and status.get("state") not in ("failed", "complete"):
                status["state"] = "failed"
                status["message"] = claim_job.get("last_error") or "Claim handoff failed"
        if module_job:
            status["module_job_id"] = module_job.get("id")
            status["module_job_status"] = module_job.get("status")
            if module_job.get("status") == "processing" and status.get("state") not in ("failed", "complete"):
                status["state"] = "generating"
                status["message"] = "Module generation is running"
            elif module_job.get("status") == "queued" and status.get("state") not in ("failed", "complete", "generating"):
                status["state"] = "module_queued"
                status["message"] = "Module generation is queued"
            elif module_job.get("status") == "failed" and status.get("state") != "complete":
                status["state"] = "failed"
                status["message"] = module_job.get("last_error") or "Module generation failed"
        rows = raw_query(
            "SELECT id, title, status, module_slug FROM missions WHERE id = %s",
            (mission_id,),
        ) or []
        if rows:
            row = rows[0]
            status.setdefault("mission_id", mission_id)
            status.setdefault("title", row.get("title", "Unknown Mission"))
            status["db_status"] = row.get("status")
            status["module_slug"] = row.get("module_slug") or ""
            if row.get("module_slug") and status.get("state") not in ("failed", "complete"):
                status["state"] = "complete"
                status["message"] = "Module is ready"
        elif not status:
            return jsonify({"error": "Mission not found"}), 404

        status.setdefault("state", "unknown")
        return jsonify({"ok": True, "status": status})
    except Exception as e:
        logger.error(f"api_claim_mission_status error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/drafts", methods=["POST"])
def api_save_draft():
    if _is_external() and not _pin_ok():
        return jsonify({"ok": False, "error": "PIN required"}), 403
    try:
        from src.db_api import db
        body   = request.get_json(force=True) or {}
        title  = body.get("title", "Untitled Draft")
        mj = json.dumps({
            "brief":       body.get("body", ""),
            "body":        body.get("body", ""),
            "source":      "dashboard",
            "difficulty":   body.get("difficulty", 5),
            "difficulty_rating": body.get("difficulty", 5),
            "mission_type": body.get("mission_type", ""),
            "party_level": body.get("party_level", ""),
            "party_size":  body.get("party_size", ""),
            "runtime":     body.get("runtime", ""),
            "personal_for": body.get("personal_for", ""),
            "options":     body.get("options", []),
        })
        db.insert("missions", {
            "title":        title,
            "faction":      body.get("faction", ""),
            "tier":         body.get("tier", "standard"),
            "difficulty":   str(body.get("difficulty", 5)),
            "status":       "active",
            "mission_json": mj,
        })
        return jsonify({"ok": True, "message": f"Draft '{title}' saved."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# /api/npcs — active NPCs
# ---------------------------------------------------------------------------

def _npc_quote(npc: dict, stats: dict) -> str:
    explicit = _pick_text(npc.get("quote"), npc.get("good_quote"), npc.get("catchphrase"), npc.get("dialogue"))
    if explicit:
        return explicit

    name = _pick_text(npc.get("name"), "This contact")
    faction = _pick_text(npc.get("faction"), "the Tower")
    role = _pick_text(npc.get("role"), "").lower()
    cls = _pick_text(stats.get("class"), npc.get("class"), "").lower()
    seed = sum(ord(c) for c in name) % 7

    if "rogue" in cls or "smuggl" in role or "agent" in role:
        quotes = [
            "Everyone has a price. The honest ones tell you which currency hurts.",
            "Walk softly here. The stones remember footsteps better than witnesses do.",
            "I can open most doors. The expensive part is closing them behind us.",
        ]
    elif "wizard" in cls or "archive" in role or "scroll" in role:
        quotes = [
            "The Tower never buries a secret. It shelves it until somebody bleeds for the catalog number.",
            "A locked book is just a confession with better manners.",
            "Ask the right question and even old ink starts telling the truth.",
        ]
    elif "fighter" in cls or "guard" in role or "patrol" in role:
        quotes = [
            "Hold the line long enough, and the city decides you were always part of the wall.",
            "Orders keep people alive. Judgment decides which orders deserve it.",
            "If trouble reaches this post, it already passed three people who looked away.",
        ]
    elif "cleric" in cls or "priest" in role or "saint" in faction.lower():
        quotes = [
            "Mercy is not soft. It simply knows where to place the blade.",
            "Bring me the wounded first. We can argue theology after they breathe.",
            "Faith is what remains when the miracle chooses someone else.",
        ]
    else:
        quotes = [
            "In this city, survival is just reputation with better boots.",
            "The Tower gives everyone a door. It rarely promises the same door twice.",
            "If you came for certainty, you took a wrong turn three districts back.",
            "Names matter here. Lose yours, and someone ambitious will wear it.",
        ]
    return quotes[seed % len(quotes)]


def _profile_image_url(path: object) -> str:
    text = _pick_text(path)
    if not text:
        return ""
    try:
        full = Path(text).resolve()
        if not full.exists():
            return ""
        root = PROJECT_ROOT.resolve()
        if not _path_within(full, root):
            return ""
        return "/media/project/" + full.relative_to(root).as_posix()
    except Exception:
        return ""


def _project_media_url(path: object, require_exists: bool = True) -> str:
    text = str(path) if isinstance(path, Path) else _pick_text(path)
    if not text:
        return ""
    try:
        full = Path(text).resolve()
        if require_exists and not full.exists():
            return ""
        root = PROJECT_ROOT.resolve()
        if not _path_within(full, root):
            return ""
        return "/media/project/" + full.relative_to(root).as_posix()
    except Exception:
        return ""


def _latest_ref_image(category: str, name: object, db_path: object = "") -> dict:
    """Resolve the current best generated image for an NPC/place/district."""
    refs = _ref_images(category, name, db_path)
    if refs:
        first = refs[0]
        return {
            "url": first.get("url", ""),
            "ref_path": first.get("ref_path", ""),
            "missing": False,
            "updated_at": first.get("updated_at", ""),
        }

    declared_url = _project_media_url(_pick_text(db_path), require_exists=False)
    return {
        "url": "",
        "ref_path": declared_url,
        "missing": bool(declared_url),
        "updated_at": "",
    }


def _ref_images(category: str, name: object, db_path: object = "") -> list[dict]:
    """Resolve all recent generated images for an NPC/place/district."""
    slug = _slug(name)
    candidates: list[Path] = []

    base_dirs = {
        "npcs": PROJECT_ROOT / "campaign_docs" / "image_refs" / "npcs",
        "npcs_alt": PROJECT_ROOT / "campaign_docs" / "image_refs" / "npcs_alt",
        "locations": PROJECT_ROOT / "campaign_docs" / "image_refs" / "locations",
    }
    base = base_dirs.get(category)
    if base and slug:
        folder = base / slug
        if folder.exists():
            candidates.extend(
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
            )

    db_text = _pick_text(db_path)
    if db_text:
        candidates.append(Path(db_text))

    unique_candidates = []
    seen = set()
    for path in candidates:
        key = str(path.resolve() if path.exists() else path)
        if key not in seen:
            seen.add(key)
            unique_candidates.append(path)

    def _ref_sort_key(path: Path) -> tuple:
        match = re.match(r"ref_(\d+)\.(?:png|jpg|jpeg|webp)$", path.name.lower())
        if match:
            return (0, int(match.group(1)))
        try:
            mtime = path.stat().st_mtime if path.exists() else 0
        except Exception:
            mtime = 0
        return (1, -mtime, path.name.lower())

    unique_candidates.sort(key=_ref_sort_key)
    refs: list[dict] = []
    for path in unique_candidates:
        url = _project_media_url(path, require_exists=True)
        if url:
            try:
                updated = path.stat().st_mtime
            except Exception:
                updated = 0
            refs.append({
                "url": url,
                "ref_path": _project_media_url(path, require_exists=False),
                "updated_at": updated,
            })
    return refs


def _serialize_npc(r: dict) -> dict:
    data = _json_obj(r.get("data_json"), {})
    app_data = _json_obj(r.get("appearance_json"), {})
    stats = _json_obj(data.get("stats"), {})
    if not isinstance(stats, dict):
        stats = {}

    equipment = data.get("equipment") or []
    if not isinstance(equipment, list):
        equipment = []
    gear = []
    for item in equipment[:18]:
        if isinstance(item, dict):
            name = _pick_text(item.get("name"), item.get("item_name"))
            if name:
                gear.append({"name": name, "equipped": bool(item.get("equipped", True)), "quantity": item.get("quantity") or 1})
        elif isinstance(item, str) and item.strip():
            gear.append({"name": item.strip(), "equipped": True, "quantity": 1})

    name = _pick_text(r.get("name"), data.get("name"), "Unknown")
    faction = _pick_text(r.get("faction"), data.get("faction"), "Independent")
    role = _pick_text(r.get("role"), data.get("role"))
    species = _pick_text(r.get("species"), data.get("species"), data.get("race"), "Unknown")
    class_name = _pick_text(stats.get("class"), data.get("class"), "No Class")
    level = stats.get("level") or data.get("level") or 0

    appearance = _pick_text(data.get("appearance"), app_data.get("appearance"), app_data.get("physical"), r.get("description"))
    motivation    = _pick_text(r.get("motivation"),    data.get("motivation"),    app_data.get("motivation"))
    relationships = _pick_text(r.get("relationships"), data.get("relationships"), app_data.get("relationships"))
    secret        = _pick_text(r.get("secret"),        data.get("secret"),        app_data.get("secret"))
    oracle_notes  = _pick_text(r.get("oracle_notes"),  data.get("oracle_notes"),  app_data.get("oracle_notes"))
    # history lives in npc_history table — fetch from DB using the row id
    _npc_db_id = r.get("id")
    if _npc_db_id:
        try:
            from src.db_api import get_npc_history as _get_hist
            history = [h["body"] for h in _get_hist(int(_npc_db_id), limit=30)]
        except Exception:
            history = []
    else:
        history = []
    public_notes = [piece for piece in [_short_text(appearance, 280)] if piece]
    if not public_notes and history:
        public_notes.append(_short_text(history[-1], 220))
    if not public_notes and role:
        public_notes.append(_short_text(role, 260))

    abilities = {key: stats.get(key) for key in ("STR", "DEX", "CON", "INT", "WIS", "CHA") if stats.get(key) is not None}
    image_ref = _latest_ref_image("npcs", name, r.get("profile_image_path"))
    alt_image_ref = _latest_ref_image("npcs_alt", name, r.get("alt_profile_image_path"))
    image_refs = _ref_images("npcs", name, r.get("profile_image_path"))
    action_image_refs = image_refs[1:]
    alt_image_refs = _ref_images("npcs_alt", name, r.get("alt_profile_image_path"))

    return {
        "id": r.get("id"),
        "name": name,
        "faction": faction,
        "role": role,
        "location": _pick_text(r.get("location"), data.get("location")),
        "status": _pick_text(r.get("status"), data.get("status"), "alive"),
        "species": species,
        "class_name": class_name,
        "level": level,
        "rank": _pick_text(r.get("rank"), data.get("rank"), app_data.get("rank")),
        "age": _pick_text(data.get("age"), app_data.get("age")),
        "style": _pick_text(data.get("style"), app_data.get("style")),
        "home_district": _pick_text(data.get("home_district")),
        "profile_image_url": image_ref.get("url", ""),
        "profile_image_urls": [ref.get("url") for ref in image_refs if ref.get("url")],
        "action_image_urls": [ref.get("url") for ref in action_image_refs if ref.get("url")],
        "profile_image_ref_path": image_ref.get("ref_path", ""),
        "profile_image_missing": image_ref.get("missing", False),
        "profile_image_updated_at": str(image_ref.get("updated_at") or r.get("profile_image_updated_at") or ""),
        "alt_profile_image_url": alt_image_ref.get("url", ""),
        "alt_profile_image_urls": [ref.get("url") for ref in alt_image_refs if ref.get("url")],
        "alt_profile_image_ref_path": alt_image_ref.get("ref_path", ""),
        "alt_profile_image_missing": alt_image_ref.get("missing", False),
        "alt_profile_image_updated_at": str(alt_image_ref.get("updated_at") or r.get("alt_profile_image_updated_at") or ""),
        "quote": _npc_quote({**data, "name": name, "faction": faction, "role": role, "quote": r.get("quote") or data.get("quote")}, stats),
        "bio": public_notes,
        "stats": {
            "ac": stats.get("AC"),
            "hp": stats.get("HP"),
            "level": level,
            "class": class_name,
            "subclass": _pick_text(stats.get("subclass")),
            "proficiency_bonus": stats.get("proficiency_bonus"),
            "abilities": abilities,
        },
        "equipment": gear,
        "motivation": motivation,
        "relationships": relationships,
        "secret": secret,
        "oracle_notes": oracle_notes,
        "statblock": {
            "speed":     stats.get("speed"),
            "skills":    stats.get("skills") or {},
            "senses":    stats.get("senses") or {},
            "languages": stats.get("languages") or [],
            "saves":     stats.get("saves") or {},
            "cr":        stats.get("cr"),
            "xp":        stats.get("xp"),
            "traits":    stats.get("traits") or [],
            "actions":   stats.get("actions") or [],
        },
        "mimir_id": _pick_text(data.get("mimir_id")),
        "history": history,
        "updated_at": str(r.get("updated_at") or ""),
    }


@app.route("/api/portraits")
def api_portraits():
    """Return portrait URLs for a batch of character names.

    Query param: names=Name1,Name2,...
    Response:    {"Name1": "/media/project/...", "Name2": "", ...}
    Empty string means no portrait found yet.
    """
    names_raw = request.args.get("names", "").strip()
    if not names_raw:
        return jsonify({})
    names = [n.strip() for n in names_raw.split(",") if n.strip()]
    result = {}
    for name in names:
        ref = _latest_ref_image("npcs", name)
        result[name] = ref.get("url", "")
    return jsonify(result)


@app.route("/api/npcs")
def api_npcs():
    try:
        from src.db_api import raw_query
        search = request.args.get("search", "").strip()
        limit = min(int(request.args.get("limit", 200)), 500)
        select_sql = (
            "SELECT n.*, "
            "(SELECT ir.image_path FROM image_refs ir "
            " WHERE ir.entity_type = 'npc_portrait' AND ir.entity_name = n.name "
            " AND ir.image_path IS NOT NULL "
            " ORDER BY COALESCE(ir.updated_at, ir.created_at) DESC LIMIT 1) AS profile_image_path, "
            "(SELECT COALESCE(ir.updated_at, ir.created_at) FROM image_refs ir "
            " WHERE ir.entity_type = 'npc_portrait' AND ir.entity_name = n.name "
            " AND ir.image_path IS NOT NULL "
            " ORDER BY COALESCE(ir.updated_at, ir.created_at) DESC LIMIT 1) AS profile_image_updated_at, "
            "(SELECT ir.image_path FROM image_refs ir "
            " WHERE ir.entity_type = 'npc_portrait_alt' AND ir.entity_name = n.name "
            " AND ir.image_path IS NOT NULL "
            " ORDER BY COALESCE(ir.updated_at, ir.created_at) DESC LIMIT 1) AS alt_profile_image_path, "
            "(SELECT COALESCE(ir.updated_at, ir.created_at) FROM image_refs ir "
            " WHERE ir.entity_type = 'npc_portrait_alt' AND ir.entity_name = n.name "
            " AND ir.image_path IS NOT NULL "
            " ORDER BY COALESCE(ir.updated_at, ir.created_at) DESC LIMIT 1) AS alt_profile_image_updated_at "
            "FROM npcs n "
        )
        if search:
            rows = raw_query(
                select_sql +
                "WHERE COALESCE(n.status, 'alive') <> 'dead' "
                "AND (n.name LIKE %s OR n.faction LIKE %s OR n.role LIKE %s OR n.location LIKE %s) "
                "ORDER BY n.name LIMIT %s",
                (f"%{search}%", f"%{search}%", f"%{search}%", f"%{search}%", limit),
            ) or []
        else:
            rows = raw_query(
                select_sql +
                "WHERE COALESCE(n.status, 'alive') <> 'dead' ORDER BY n.name LIMIT %s",
                (limit,),
            ) or []
        return jsonify({"npcs": [_serialize_npc(r) for r in rows], "count": len(rows)})
    except Exception as e:
        return jsonify({"npcs": [], "count": 0, "error": str(e)})


@app.route("/api/npcs/<path:npc_name>")
def api_npc_detail(npc_name: str):
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT n.*, "
            "(SELECT ir.image_path FROM image_refs ir "
            " WHERE ir.entity_type = 'npc_portrait' AND ir.entity_name = n.name "
            " AND ir.image_path IS NOT NULL "
            " ORDER BY COALESCE(ir.updated_at, ir.created_at) DESC LIMIT 1) AS profile_image_path, "
            "(SELECT COALESCE(ir.updated_at, ir.created_at) FROM image_refs ir "
            " WHERE ir.entity_type = 'npc_portrait' AND ir.entity_name = n.name "
            " AND ir.image_path IS NOT NULL "
            " ORDER BY COALESCE(ir.updated_at, ir.created_at) DESC LIMIT 1) AS profile_image_updated_at, "
            "(SELECT ir.image_path FROM image_refs ir "
            " WHERE ir.entity_type = 'npc_portrait_alt' AND ir.entity_name = n.name "
            " AND ir.image_path IS NOT NULL "
            " ORDER BY COALESCE(ir.updated_at, ir.created_at) DESC LIMIT 1) AS alt_profile_image_path, "
            "(SELECT COALESCE(ir.updated_at, ir.created_at) FROM image_refs ir "
            " WHERE ir.entity_type = 'npc_portrait_alt' AND ir.entity_name = n.name "
            " AND ir.image_path IS NOT NULL "
            " ORDER BY COALESCE(ir.updated_at, ir.created_at) DESC LIMIT 1) AS alt_profile_image_updated_at "
            "FROM npcs n WHERE n.name = %s LIMIT 1",
            (npc_name,),
        ) or []
        if not rows:
            return jsonify({"error": "not found"}), 404
        return jsonify({"npc": _serialize_npc(rows[0]), "ok": True})
    except Exception as e:
        return jsonify({"error": str(e), "ok": False}), 500


# ---------------------------------------------------------------------------
# /api/districts — gazetteer districts
# ---------------------------------------------------------------------------

@app.route("/api/districts")
def api_districts():
    """List all districts — reads from gazetteer table (DB authoritative)."""
    try:
        from src.db_api import raw_query
        # Pull district metadata from gazetteer JSON blob
        rows = raw_query("SELECT content_json FROM gazetteer LIMIT 1")
        gaz_districts: dict = {}
        if rows:
            gaz = rows[0]["content_json"]
            if isinstance(gaz, str):
                gaz = json.loads(gaz)
            gaz_districts = gaz.get("districts", {})

        # Pull place counts per district from normalised table
        counts = raw_query(
            "SELECT district, COUNT(*) as cnt FROM gazetteer_places GROUP BY district"
        ) or []
        place_counts = {r["district"]: r["cnt"] for r in counts}

        # Pull districts that have generated area profiles
        try:
            profile_rows = raw_query("SELECT district FROM area_profiles") or []
            has_profile = {r["district"] for r in profile_rows}
        except Exception:
            has_profile = set()

        image_rows = raw_query(
            "SELECT entity_name, image_path, updated_at FROM image_refs "
            "WHERE entity_type IN ('location_map', 'area_map') AND image_path IS NOT NULL "
            "ORDER BY COALESCE(updated_at, created_at) DESC"
        ) or []
        # Build two indexes:
        #  slug_images  — exact slug match (district name → image)
        #  word_images  — each significant word in entity_name → image list
        #                 used for fuzzy match when no exact slug match exists
        slug_images: dict[str, dict] = {}
        word_images: dict[str, list] = {}
        for img in image_rows:
            raw_name = img.get("entity_name") or ""
            key = _slug(raw_name)
            if not key:
                continue
            ref = _latest_ref_image("locations", raw_name, img.get("image_path"))
            entry = {
                "image_url":      ref.get("url", ""),
                "image_urls":     [r.get("url") for r in _ref_images("locations", raw_name, img.get("image_path")) if r.get("url")],
                "image_ref_path": ref.get("ref_path", ""),
                "image_missing":  ref.get("missing", False),
                "image_updated_at": str(img.get("updated_at") or ref.get("updated_at") or ""),
                "_entity_words":  set(re.findall(r'[a-z]{4,}', raw_name.lower())),
            }
            if key not in slug_images:
                slug_images[key] = entry
            # Index each word (≥4 chars) for fuzzy district matching
            for word in re.findall(r'[a-z]{4,}', raw_name.lower()):
                word_images.setdefault(word, []).append(entry)

        def _district_image(district_name: str) -> dict:
            """Return best image dict for a district, or {}."""
            # 1. Exact slug match
            hit = slug_images.get(_slug(district_name))
            if hit and hit.get("image_url"):
                return hit
            # 2. Fuzzy: score candidates by word overlap — ALL district words must
            #    appear in the entity name to avoid cross-contamination between
            #    places that share a single word (e.g. "Grand Forum" vs "Grand Pit").
            district_words = set(re.findall(r'[a-z]{4,}', district_name.lower()))
            if not district_words:
                return {}
            best_score, best_entry = 0, None
            seen_ids: set[int] = set()
            for word in district_words:
                for c in word_images.get(word, []):
                    cid = id(c)
                    if cid in seen_ids or not c.get("image_url"):
                        continue
                    seen_ids.add(cid)
                    overlap = len(district_words & c.get("_entity_words", set()))
                    if overlap > best_score:
                        best_score, best_entry = overlap, c
            # Only accept if ALL district words matched — no partial contamination
            if best_entry and best_score >= len(district_words):
                return best_entry
            return {}

        districts = []
        for name, info in gaz_districts.items():
            fp = info.get("faction_presence", [])
            if isinstance(fp, str):
                try:
                    fp = json.loads(fp.replace("'", '"'))
                except Exception:
                    fp = []
            image = _district_image(name)
            districts.append({
                "name": name,
                "ring": info.get("ring"),
                "danger_level": info.get("danger_level"),
                "faction_presence": fp,
                "description": info.get("description", ""),
                "place_count": place_counts.get(name, 0),
                "has_profile": name in has_profile,
                "image_url": image.get("image_url", ""),
                "image_urls": image.get("image_urls", []),
                "image_ref_path": image.get("image_ref_path", ""),
                "image_missing": image.get("image_missing", False),
                "image_updated_at": image.get("image_updated_at", ""),
            })

        # Sort by ring then name
        districts.sort(key=lambda d: (str(d.get("ring") or "99"), d["name"]))
        return jsonify({"districts": districts, "count": len(districts)})
    except Exception as e:
        return jsonify({"districts": [], "count": 0, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/districts/<name>/places — all places in a district from DB
# ---------------------------------------------------------------------------

@app.route("/api/districts/<district_name>/places")
def api_district_places(district_name: str):
    """Return all gazetteer_places rows for a district, grouped by type."""
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT id, district, place_type, name, type_tag, description, extra_json, wealth_level"
            " FROM gazetteer_places WHERE district = %s ORDER BY place_type, name",
            (district_name,),
        ) or []
        image_rows = raw_query(
            "SELECT entity_name, image_path, updated_at FROM image_refs "
            "WHERE entity_type IN ('location_map', 'area_map') AND image_path IS NOT NULL "
            "ORDER BY COALESCE(updated_at, created_at) DESC"
        ) or []
        image_lookup: dict[str, dict] = {}
        for img in image_rows:
            ref = _latest_ref_image("locations", img.get("entity_name"), img.get("image_path"))
            refs = _ref_images("locations", img.get("entity_name"), img.get("image_path"))
            image_url = ref.get("url", "")
            declared_url = ref.get("ref_path", "")
            image_missing = ref.get("missing", False)
            if not image_url and not image_missing:
                continue
            names = {_pick_text(img.get("entity_name")).lower(), _slug(img.get("entity_name"))}
            for key in names:
                if key and key not in image_lookup:
                    image_lookup[key] = {
                        "url": image_url,
                        "urls": [r.get("url") for r in refs if r.get("url")],
                        "ref_path": declared_url,
                        "missing": image_missing,
                        "updated_at": str(img.get("updated_at") or ""),
                    }

        grouped: dict[str, list] = {}
        for r in rows:
            pt = r["place_type"]
            if pt not in grouped:
                grouped[pt] = []
            keys = [
                _pick_text(r.get("name")).lower(),
                _slug(r.get("name")),
                _slug(f"{r.get('district')} {r.get('name')}"),
            ]
            image = next((image_lookup[k] for k in keys if k in image_lookup), {})
            entry = {
                "id": r.get("id"),
                "district": r.get("district"),
                "place_type": pt,
                "name": r["name"],
                "type_tag": r["type_tag"] or "",
                "description": r["description"] or "",
                "wealth_level": r.get("wealth_level"),
                "image_url": image.get("url", ""),
                "image_urls": image.get("urls", []),
                "image_ref_path": image.get("ref_path", ""),
                "image_missing": image.get("missing", False),
                "image_updated_at": image.get("updated_at", ""),
            }
            if r["extra_json"]:
                ex = r["extra_json"]
                if isinstance(ex, str):
                    try:
                        ex = json.loads(ex)
                    except Exception:
                        ex = {}
                entry["extra"] = ex
            grouped[pt].append(entry)
        return jsonify({"district": district_name, "places": grouped, "total": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# /api/districts/<name>/profile — LLM-generated area profile
# ---------------------------------------------------------------------------

@app.route("/api/districts/<district_name>/profile")
def api_district_profile(district_name: str):
    """Return the area_profiles entry for a district if it exists."""
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT profile_json, generated_at FROM area_profiles WHERE district = %s LIMIT 1",
            (district_name,),
        )
        if not rows or not rows[0]["profile_json"]:
            return jsonify({"profile": None})
        pj = rows[0]["profile_json"]
        if isinstance(pj, str):
            pj = json.loads(pj)
        return jsonify({"profile": pj, "generated_at": str(rows[0].get("generated_at", ""))})
    except Exception as e:
        return jsonify({"profile": None, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/factions — faction list
# ---------------------------------------------------------------------------

FACTIONS = [
    "Iron Fang Consortium",
    "Argent Blades",
    "Wardens of Ash",
    "Serpent Choir",
    "Obsidian Lotus",
    "Glass Sigil",
    "Patchwork Saints",
    "Adventurers Guild",
    "Guild of Ashen Scrolls",
    "Tower Authority / FTA",
    "Wizards Tower",
    "Brother Thane's Cult",
]


@app.route("/api/factions")
def api_factions():
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT faction_name, reputation_score, tier, leader, description FROM faction_reputation ORDER BY reputation_score DESC"
        ) or []
        seen: set = set()
        result = []
        for r in rows:
            name = (r.get("faction_name") or "").strip()
            # Skip bracketed alias rows, slash-alias variants, and Unknown
            if not name or name.startswith("[") or " / " in name or name == "Unknown":
                continue
            if name in seen:
                continue
            seen.add(name)
            result.append({
                "name":        name,
                "score":       r.get("reputation_score", 0),
                "tier":        r.get("tier", "neutral"),
                "leader":      r.get("leader", ""),
                "description": r.get("description", ""),
            })
        # Append hardcoded factions that aren't in DB at all (intentional extras)
        for f in FACTIONS:
            if f not in seen:
                result.append({"name": f, "score": 0, "tier": "neutral", "leader": "", "description": ""})
        return jsonify({"factions": result})
    except Exception as e:
        return jsonify({"factions": [{"name": f} for f in FACTIONS], "error": str(e)})


# ---------------------------------------------------------------------------
# /api/bulletins — recent bulletins from bulletin_cache
# ---------------------------------------------------------------------------

@app.route("/api/bulletins")
def api_bulletins():
    try:
        from src.db_api import raw_query
        from src.text_mojibake import repair_payload
        rows = raw_query(
            "SELECT bulletin_id, payload, created_at FROM bulletin_cache "
            "ORDER BY created_at DESC LIMIT 20"
        ) or []
        results = []
        for row in rows:
            data = row.get("payload") or {}
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except Exception:
                    data = {}
            data = repair_payload(data)
            results.append({
                "id": row.get("bulletin_id"),
                "headline": data.get("headline", ""),
                "bulletin_type": data.get("bulletin_type", "news"),
                "preview": data.get("preview", "")[:200],
                "full_content": data.get("full_content", ""),
                "created_at": str(row.get("created_at", "")),
            })
        return jsonify({"bulletins": results})
    except Exception as e:
        return jsonify({"bulletins": [], "error": str(e)})


# ---------------------------------------------------------------------------
# /api/generate-mission — generate a mission via the mission builder
# ---------------------------------------------------------------------------

def _is_external():
    """True when request arrives via Cloudflare tunnel (has CF-Ray header)."""
    return bool(request.headers.get("CF-Ray") or request.headers.get("Cf-Ray"))


def _pin_ok(data: dict | None = None) -> bool:
    """Validate the dashboard action PIN for external requests."""
    expected = os.getenv("DASHBOARD_EXTERNAL_PIN", "86753").strip()
    if not expected:
        return True
    data = data or {}
    supplied = (
        data.get("pin")
        or request.headers.get("X-Dashboard-Pin")
        or request.args.get("pin")
        or ""
    )
    return str(supplied).strip() == expected


@app.route("/api/view-mode")
def api_view_mode():
    return jsonify({"readonly": _is_external()})


@app.route("/api/log-bug", methods=["POST"])
def api_log_bug():
    """Append a web-UI error entry to buglog.md."""
    if _is_external() and not _pin_ok():
        return jsonify({"ok": False, "error": "PIN required"}), 403
    data    = request.get_json(force=True) or {}
    message = (data.get("message") or "").strip()
    context = (data.get("context") or "").strip()
    if not message:
        return jsonify({"ok": False, "error": "message required"}), 400
    try:
        from datetime import datetime as _dt
        buglog = PROJECT_ROOT / "buglog.md"
        ts     = _dt.now().strftime("%Y-%m-%d %H:%M")
        entry  = f"\n## Web UI Error — {ts}\n**Context:** {context or 'Mission Generator'}\n**Error:** {message}\n"
        with open(buglog, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.warning(f"[BUGLOG] {context}: {message}")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/generate-mission", methods=["POST"])
def api_generate_mission():
    """
    Generate a single mission contract posting via the Undercity mission board pipeline.

    Body (JSON):
        faction: str          — sponsoring faction (empty = any)
        tier: str             — difficulty tier label
        mission_type: str     — one of the supported mission pipeline types
        title: str            — optional seed title
        body: str             — DM brief to write from
        difficulty: int       — 1-10
        party_size: int
        party_level: int
        runtime: str
        personal_for: str     — character name if personal mission
    """
    if _is_external():
        return jsonify({"error": "Mission generation is disabled for external access."}), 403

    import asyncio
    import concurrent.futures
    from src.mission_board import (
        _LORE,
        _build_npc_context,
        _load_area_context_block,
        _load_missions,
        _normalise_rotation_faction,
        _pick_rotation_faction,
    )

    data         = request.get_json(force=True) or {}
    faction      = (data.get("faction") or "").strip()
    tier         = (data.get("tier") or "standard").strip()
    mission_type = (data.get("mission_type") or "Investigation").strip()
    difficulty   = int(data.get("difficulty") or 5)
    dm_brief     = (data.get("body") or "").strip()
    title_seed   = (data.get("title") or "").strip()
    party_size   = data.get("party_size", 4)
    party_level  = data.get("party_level", 5)
    runtime           = (data.get("runtime") or "7 days").strip()
    personal_for      = (data.get("personal_for") or "").strip()
    opposing_faction  = (data.get("opposing_faction") or "").strip()

    try:
        from src.mission_builder.locations import find_location_for_mission, build_location_context
        from src.agents.kimi_agent import KimiAgent

        requested_faction = faction
        rotation_faction = _pick_rotation_faction(_load_missions()) if not requested_faction else requested_faction
        location_name, _ = find_location_for_mission(faction=rotation_faction or None, tier=tier)
        location_ctx  = build_location_context(location_name)
        npc_block     = _build_npc_context()
        area_block    = _load_area_context_block()
        world_context = _mission_generation_context_block()

        brief_section    = f"\nDM BRIEF — write the mission from this seed:\n{dm_brief}\n" if dm_brief else ""
        title_section    = f"\nTitle seed (use as inspiration, rewrite to match rules): {title_seed}\n" if title_seed else ""
        personal_section = (
            f"\nPERSONAL MISSION for: {personal_for}. "
            "The contact must know this character specifically. Make the stakes personal to them.\n"
        ) if personal_for else ""
        opposing_section = (
            f"\nOPPOSING FACTION/THREAT: {opposing_faction}. "
            "Include this as the *Opposes:* line and work it into the stakes naturally.\n"
        ) if opposing_faction else ""

        prompt = f"""{_LORE}

{npc_block}
{area_block}

{world_context}

---
You are the Undercity mission board. Generate ONE mission contract posting.

MISSION PARAMETERS:
- Faction: {rotation_faction}
- Mission type: {mission_type}
- Tier: {tier} (difficulty {difficulty}/10 — {_difficulty_to_rank(difficulty)} rank)
- Location area: {location_name}
- Party: {party_size} adventurers, level {party_level}
- Runtime: {runtime}
{title_section}{brief_section}{personal_section}{opposing_section}
LOCATION CONTEXT:
{location_ctx}

REQUIRED FORMAT — output exactly this structure, nothing else:

**[FACTION NAME] — MISSION TITLE**
*Type: {mission_type} | Tier: [tier label] | Expires: TBD | Reward: [X EC + optional Kharma]*
*Opposes: [faction name, or "None"]*

[1-2 brief surface-level sentences:
  SENTENCE 1: The public situation — what help is needed, who is involved, specific place.
  SENTENCE 2 (optional): The public stakes or visible oddity. Do not include hidden clues, solution details, or module-only information.]

*Contact: [NPC name from the list above], [location] — [one detail: what they lose if this fails, or what they won't tell you]*

SURFACE-LEVEL BULLETIN RULE:
- Mission bulletins are public contract notices only.
- Do NOT reveal hidden truths, puzzle solutions, answer keys, solve paths, secret motives, map plans, encounter mechanics, or module-only details.
- For Puzzle missions, describe only the visible puzzle source/problem and why help is needed. Never reveal how it is solved.
- For Strange Occurrences, describe only the public weirdness and civic/coroner concern. Do not reveal whether the ghost, returned dead, or doppelganger is guilty, innocent, or protecting someone.
- For First Contact, describe only the immediate contact problem, protection need, or communication barrier. Do not reveal cultural secrets or the best solution.
- For Discovery, describe only the visible anomaly/object/phenomenon and why careful handling is needed. Do not reveal the implication tree or final truth.
- For Exploration, describe only the place to survey and visible risk. Do not reveal hidden discoveries.
- For Recovery, describe only what is lost/misplaced/stolen and why return matters. Do not reveal who has it, how to retrieve it, or whether ownership is morally complicated.

TITLE RULES:
- Maximum 6 words. Must contain at least one proper noun: a district name, street, NPC name, guild, or specific object.
- Title must feel like a case file, public incident, debt marker, named route, named victim, named venue, or named object from the live context. Avoid mythic fantasy abstraction.
- Do not reuse the rhythm, nouns, or symbols of any recent title listed in LIVE WORLD CONTEXT. Especially avoid more crowns, relics, plows, generic ledgers, generic shadows, or generic secrets unless the exact object/person appears in live context.
- STRUCTURAL VARIETY — each title should use one of these patterns (vary them, do not always use "The [Adj] [Noun]"):
    PERSON/PLACE: "Dust Market Strangler", "Kaelth's Missing Invoice", "Thorn Quarter Body Count"
    STATE + LOCATION: "Fungal Bloom at the Pillar", "Dead Warden, Cobbleway North"
    OBJECT + CONTEXT: "Bones in the Clockwork Spire", "Unsigned Ledger, Coroner's Office"
    COUNT/NUMBER: "Warden's Forge Missing Three", "Four Vials, One Chemist"
    POSSESSIVE + EVENT: "Glass Sigil's Vanished Courier", "Iron Fang's Unpaid Debt"
    IMPERATIVE/JOB: "Recover the Pillar Mosaic", "Find Who Lit the Pyre"
- Good context-built title examples: "Mira Kaelth Owes Hearthstone", "Third Bell at Neon Row", "Find Havel's Missing Witness", "Iron Fang Audit Night", "Courier Down, Cobbleway East"
- BANNED patterns: "The [Adjective] [Abstract Noun]" — no "The Silent X", "The Dark X", "The Burning X", "The Smoldering X", "The Hollow X"
- BANNED words in titles unless they are exact live-context proper nouns: Crown, Crowns, Relic, Relics, Plow, Plows, Harvest, Shadow, Shadows, Darkness, Silence, Reckoning, Unraveling, Corruption, Awakening, Legacy, Revelation, Convergence, Resonance, Void, Abyss, Storm, Tide, Forgotten, Ancient, Flame, Crimson, Obsidian (unless it IS the Obsidian Lotus faction name)
- BANNED structure: do not start with "The" unless followed immediately by a proper noun ("The Pillar" OK, "The Burning Secret" not OK)

PROSE RULES:
- Noir city dispatch. Every sentence names a specific place, person, or thing.
- The posting must be contextually built from live news, previous mission fallout, council decisions, or the DM brief. Mention at least one named consequence chain without exposing hidden module truth.
- Keep the public bulletin short. It should tease the job, not explain it.
- SENSORY BEAT IS OPTIONAL and must stay public-facing:
    GOOD: "The archive still smells of burnt parchment — someone left scrolls charred at the edges."
    GOOD: "The Pillar's mosaic cracks with the scent of burnt incense. Someone lit a pyre last night."
    BAD: "An ancient darkness stirs..." / "Shadows fall across the district..."
- STAKES must be personal: "Mira Kaelth will lose her position" beats "trade routes disrupted"
- CONTACT must have skin in the game — what they lose if the party fails

RULES:
- Use one listed NPC as contact or antagonist. Do NOT invent faction leaders.
- Tier label (use exactly one): local, patrol, standard, investigation, rift, dungeon, major, inter-guild, high-stakes, epic, divine, tower
- If Mission type is Heist, make the target, handler, fence, or hidden beneficiary shady if needed; do not change the posting faction away from {rotation_faction}.
- If Mission type is Strange Occurrences, the coroner's office, death registry, morgue, cemetery authority, or a worried civic/family contact should usually be involved; sketchy guild sponsors are rare.
- If Mission type is Assault, the target is a fixed position and the public goal is to take, seize, or breach that position.
- If Mission type is Infestation, the public post should name the visible spread, nest, or signs without revealing the hidden source.
- If Mission type is Recovery, do not make a living person the main target. Use evidence, relics, lost gear, memory/identity packets, data/records, misplaced cargo, or missing pets.
- Rift tier ONLY in Warrens or Outer Wall. Never elsewhere.
- Rewards within hard limits. No Kharma over 1200.
- No preamble. No sign-off. Mission post only."""

        # Run async agent in a fresh event loop via thread executor to avoid Flask loop conflicts.
        # IMPORTANT: src/ollama_queue.py creates asyncio.Lock objects at module level, so they
        # are bound to whichever event loop was current at import time.  We must rebind them to
        # the new loop before calling any code that uses them, otherwise asyncio raises
        # "Lock is bound to a different event loop".
        def _run_agent():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                import src.ollama_queue as _oq
                _oq._lock       = asyncio.Lock()
                _oq._quick_lock = asyncio.Lock()
                agent = KimiAgent()
                resp  = loop.run_until_complete(agent.complete(prompt=prompt, temperature=0.88))
                loop.run_until_complete(agent.close())
                return resp
            finally:
                loop.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future   = ex.submit(_run_agent)
            response = future.result(timeout=600)

        if not response.success:
            return jsonify({"error": response.error or "Agent returned no content"}), 500

        content = response.content.strip()

        # Strip any BEAT labels the model echoed back
        import re as _re
        content = _re.sub(r'\bBEAT\s+\d+\s*[—–-]\s*(?:SITUATION|SENSORY ANCHOR|STAKES|HOOK)?[:\s]*',
                          '', content, flags=_re.IGNORECASE)
        content = _re.sub(r'\bHOOK\s*[—–-]\s*', '', content, flags=_re.IGNORECASE)
        content = _re.sub(r'\n{3,}', '\n\n', content).strip()

        # Parse structured fields from the formatted output
        title_m   = _re.search(r'\*\*(.+?)\*\*', content)
        type_m    = _re.search(r'[Tt]ype:\s*([^\|\n\*]+)', content)
        tier_m    = _re.search(r'[Tt]ier:\s*([a-z\-]+)', content)
        reward_m  = _re.search(r'[Rr]eward:\s*([^\n\|\*]+)', content)
        contact_m = _re.search(r'\*Contact:\s*(.+?)(?:\*|$)', content, _re.IGNORECASE | _re.MULTILINE)
        opposes_m = _re.search(r'[Oo]pposes:\s*([^\n\|\*]+)', content)

        raw_title   = title_m.group(1) if title_m else ""
        fac_parsed  = raw_title.split("—")[0].strip() if "—" in raw_title else faction
        title_final = raw_title.split("—")[-1].strip() if raw_title else "Unknown"
        type_parsed = type_m.group(1).strip().rstrip("|").strip() if type_m else mission_type
        faction_final = requested_faction or _normalise_rotation_faction(fac_parsed)
        if faction_final != rotation_faction:
            logger.warning(
                f"dashboard generate-mission: faction override '{faction_final}' -> '{rotation_faction}'"
            )
            faction_final = rotation_faction

        tier_val = tier_m.group(1).strip() if tier_m else tier
        mission_data = {
            "title":    title_final,
            "faction":  faction_final,
            "type":     type_parsed,
            "tier":     tier_val,
            "reward":   reward_m.group(1).strip() if reward_m else "",
            "contact":  contact_m.group(1).strip() if contact_m else "",
            "location": location_name,
            "opposing_faction": opposes_m.group(1).strip() if opposes_m else opposing_faction,
            "body":     content,
            "source":   "dashboard",
        }

        # Save the bulletin to the missions table so it appears on the board
        mission_id = None
        try:
            from src.db_api import db as _db
            import json as _json
            mj = _json.dumps({
                "title":         title_final,
                "faction":       faction_final,
                "tier":          tier_val,
                "difficulty":    difficulty,
                "difficulty_rating": difficulty,
                "type":          type_parsed,    # generate_module routes on mission.get("type")
                "mission_type":  type_parsed,    # fallback key used by some pipeline helpers
                "brief":         content,
                "body":          content,
                "source":        "dashboard",
                "party_level":   party_level,
                "party_size":    party_size,
                "runtime":       runtime,
                "personal_for":  personal_for,
                "location":      location_name,
                "contact":       mission_data["contact"],
                "opposing_faction": mission_data["opposing_faction"],
                "reward":        mission_data["reward"],
            })
            mission_id = _db.insert("missions", {
                "title":        title_final,
                "faction":      faction_final,
                "tier":         tier_val,
                "difficulty":   str(difficulty),
                "status":       "active",
                "mission_json": mj,
            })
        except Exception as save_err:
            logger.warning(f"api_generate_mission: DB save failed (non-fatal): {save_err}")

        return jsonify({"mission": mission_data, "ok": True, "raw": content, "mission_id": mission_id})

    except concurrent.futures.TimeoutError:
        return jsonify({"error": "Generation timed out (10 min). Ollama may be busy.", "ok": False}), 504
    except Exception as e:
        logger.error(f"api_generate_mission error: {e}", exc_info=True)
        return jsonify({"error": str(e), "ok": False}), 500


@app.route("/api/post-mission-to-discord", methods=["POST"])
def api_post_mission_to_discord():
    """
    Post a generated mission bulletin to the Discord mission board channel.

    Uses the Discord REST API directly (no bot process required).
    Adds the ⚔️ claim reaction after posting.

    Body (JSON):
        mission:    dict  — mission fields (title, faction, type, tier, reward, contact, body, opposing_faction)
        mission_id: int   — optional DB row id to update with the discord message_id
    """
    if _is_external():
        return jsonify({"error": "Posting is disabled for external access."}), 403

    import urllib.request as _urlreq
    import json as _json

    token      = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv("MISSION_BOARD_CHANNEL_ID", "")
    if not token:
        return jsonify({"error": "DISCORD_BOT_TOKEN not configured"}), 500
    if not channel_id:
        return jsonify({"error": "MISSION_BOARD_CHANNEL_ID not configured"}), 500

    data       = request.get_json(force=True) or {}
    mission    = data.get("mission") or {}
    mission_id = data.get("mission_id")

    title    = mission.get("title", "Unknown Mission")
    faction  = mission.get("faction", "")
    mtype    = mission.get("type", mission.get("mission_type", "Mission"))
    tier     = mission.get("tier", "standard").title()
    reward   = mission.get("reward", "See posting")
    contact  = mission.get("contact", "")
    opposing = mission.get("opposing_faction", "")
    body     = mission.get("body", "")

    # Strip markdown and truncate for embed description
    import re as _re
    story = _re.sub(r'\*+', '', body).strip()
    # Remove header line (faction — title) if echoed in body
    story = _re.sub(r'^[^\n]+—[^\n]+\n', '', story).strip()
    # Remove metadata lines (*Type: ... | Tier: ...*  and  *Contact: ...*  and  *Opposes: ...*)
    story = _re.sub(r'^\*[^\n]+\*\s*$', '', story, flags=_re.MULTILINE).strip()
    story = _re.sub(r'\n{2,}', '\n\n', story).strip()
    if len(story) > 700:
        story = story[:697].rsplit(" ", 1)[0] + "…"

    # Tier-based embed colour (mirrors faction_reputation palette roughly)
    tier_colors = {
        "local": 0x6b7f6b, "patrol": 0x7a8c7a, "standard": 0x8f7a5a,
        "investigation": 0x5a7a8f, "rift": 0x8f5a7a, "dungeon": 0x5a6b8f,
        "major": 0xb87a3a, "inter-guild": 0xb8923a, "high-stakes": 0xcc6633,
        "epic": 0xcc3333, "divine": 0xb8a020, "tower": 0x8f3a8f,
    }
    color = tier_colors.get(mission.get("tier", "standard").lower(), 0xE6C300)

    footer_parts = [f"⚔ {mtype}", f"Tier: {tier}", "React ⚔️ to claim"]
    if opposing:
        footer_parts.append(f"Opposes: {opposing}")

    embed = {
        "title":       title,
        "description": story,
        "color":       color,
        "author":      {"name": faction} if faction else None,
        "fields": [
            {"name": "Type",   "value": mtype,  "inline": True},
            {"name": "Tier",   "value": tier,   "inline": True},
            {"name": "Reward", "value": reward, "inline": True},
        ],
        "footer": {"text": "  •  ".join(footer_parts)},
    }
    if contact:
        embed["fields"].append({"name": "Contact", "value": contact, "inline": False})
    if opposing:
        embed["fields"].append({"name": "⚠️ Opposes", "value": opposing, "inline": False})
    if embed["author"] is None:
        del embed["author"]

    def _discord_request(method, url, body=None):
        """Minimal Discord REST call using only stdlib — no asyncio dependency."""
        data = _json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
        req  = _urlreq.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type":  "application/json",
                "User-Agent":    "TowerBot/1.0",
            },
            method=method,
        )
        try:
            with _urlreq.urlopen(req, timeout=15) as resp:
                raw = resp.read()
                return resp.status, _json.loads(raw) if raw else {}
        except _urlreq.HTTPError as e:
            return e.code, {}

    try:
        base = f"https://discord.com/api/v10/channels/{channel_id}"

        status, msg = _discord_request("POST", f"{base}/messages", {"embeds": [embed]})
        if status not in (200, 201):
            return jsonify({"error": f"Discord returned {status}"}), 502

        message_id = msg["id"]

        # Add ⚔️ claim reaction (204 = success, ignore failures)
        _discord_request("PUT", f"{base}/messages/{message_id}/reactions/%E2%9A%94%EF%B8%8F/@me")

        # Update DB row with discord message/channel ids.
        # message_id must be written to BOTH mission_json["message_id"] AND the
        # missions.message_id column — _load_missions() reads both and uses whichever
        # is non-null. Without this, handle_reaction_claim() can't find the mission
        # and silently returns without triggering module generation.
        if mission_id:
            try:
                from src.db_api import db as _db
                row = _db.fetch_one("SELECT mission_json FROM missions WHERE id = %s", (mission_id,))
                if row:
                    mj = _json.loads(row["mission_json"] or "{}")
                    mj["discord_message_id"] = message_id
                    mj["discord_channel_id"] = channel_id
                    mj["message_id"] = message_id   # key _load_missions() merges into dict
                    _db.update("missions", {
                        "mission_json": _json.dumps(mj),
                        "message_id":   str(message_id),   # DB column the bot indexes on
                    }, {"id": mission_id})
            except Exception as db_err:
                logger.warning(f"post-mission-to-discord: DB update failed (non-fatal): {db_err}")

        return jsonify({"ok": True, "message_id": message_id, "channel_id": channel_id})

    except Exception as e:
        logger.error(f"api_post_mission_to_discord error: {e}", exc_info=True)
        return jsonify({"error": str(e), "ok": False}), 500


def _difficulty_to_rank(difficulty: int) -> str:
    """Convert 1-10 difficulty int to S/A/B/C/D/E rank."""
    if difficulty >= 9: return "S"
    if difficulty >= 7: return "A"
    if difficulty >= 5: return "B"
    if difficulty >= 3: return "C"
    if difficulty >= 2: return "D"
    return "E"


# ---------------------------------------------------------------------------
# /api/complete-mission — tablet debrief form submission
# ---------------------------------------------------------------------------

@app.route("/api/complete-mission", methods=["POST"])
def api_complete_mission():
    """
    Accept a debrief form from session.html and write the outcome to DB.
    Also flips missions.status to 'completed' or 'failed'.
    Works from both localhost and Cloudflare tunnel.
    """
    data   = request.get_json(force=True) or {}
    if _is_external() and not _pin_ok(data):
        return jsonify({"ok": False, "error": "PIN required"}), 403
    title  = (data.get("mission_title") or "").strip()
    mid    = data.get("mission_id")
    result = data.get("result", "completed")
    if result not in ("completed", "failed"):
        result = "completed"

    if not mid and not title:
        return jsonify({"ok": False, "error": "mission_id required"}), 400

    try:
        from src.db_api import raw_query, raw_execute, db
        from datetime import datetime

        # Resolve mission by id first (preferred), fall back to title only if no id
        mission_row = None
        if mid:
            rows = raw_query(
                "SELECT id, title, status FROM missions WHERE id=%s LIMIT 1", (int(mid),)
            )
            if rows:
                mission_row = rows[0]
                title = mission_row["title"]
        if not mission_row and title:
            # Title fallback: require exactly one match to avoid wrong-row writes
            rows = raw_query(
                "SELECT id, title, status FROM missions WHERE title=%s", (title,)
            )
            if len(rows) == 1:
                mission_row = rows[0]
                mid = mission_row["id"]
            elif len(rows) > 1:
                return jsonify({
                    "ok": False,
                    "error": f"Ambiguous title — {len(rows)} missions match '{title}'. Provide mission_id."
                }), 409

        if not mission_row:
            return jsonify({"ok": False, "error": "Mission not found"}), 404

        # Write to mission_outcomes — prefer mission_id identity over title
        outcome_fields = {
            "mission_id":       int(mid) if mid else None,
            "mission_title":    title,
            "result":           result,
            "completed_by":     (data.get("completed_by") or "").strip(),
            "completed_at":     datetime.now().strftime("%Y-%m-%d"),
            "npcs_killed":      (data.get("npcs_killed") or "").strip(),
            "key_decisions":    (data.get("key_decisions") or "").strip(),
            "location_changes": (data.get("location_changes") or "").strip(),
            "loose_threads":    (data.get("loose_threads") or "").strip(),
            "notable_moments":  (data.get("notable_moments") or "").strip(),
            "consequences_json": "[]",
        }
        # Lookup existing outcome: by mission_id if we have one, else title only for legacy null rows
        if mid:
            existing = raw_query(
                "SELECT id FROM mission_outcomes WHERE mission_id=%s LIMIT 1", (int(mid),)
            )
        else:
            existing = raw_query(
                "SELECT id FROM mission_outcomes WHERE mission_id IS NULL AND mission_title=%s LIMIT 1",
                (title,),
            )
        if existing:
            oid = existing[0]["id"]
            set_clause = ", ".join(f"{k}=%s" for k in outcome_fields if k not in ("mission_id", "mission_title"))
            vals = [v for k, v in outcome_fields.items() if k not in ("mission_id", "mission_title")] + [oid]
            raw_execute(f"UPDATE mission_outcomes SET {set_clause} WHERE id=%s", vals)
            if mid:
                raw_execute("UPDATE mission_outcomes SET mission_id=%s WHERE id=%s", (int(mid), oid))
        else:
            db.insert("mission_outcomes", {k: v for k, v in outcome_fields.items() if v is not None or k != "mission_id"})

        # Flip mission status by id only — never by title
        status_val = "completed" if result == "completed" else "failed"
        raw_execute(
            "UPDATE missions SET status=%s WHERE id=%s",
            (status_val, int(mid)),
        )

        app.logger.info(f"📋 Session debrief submitted: id={mid} '{title}' → {status_val}")
        return jsonify({"ok": True, "status": status_val, "mission_id": mid})

    except Exception as e:
        app.logger.error(f"api_complete_mission error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# /api/places — search across all gazetteer places
# ---------------------------------------------------------------------------

@app.route("/api/places")
def api_places():
    place_type = request.args.get("type")  # place_of_interest | small_shop | park | mall
    district = request.args.get("district")
    limit = min(int(request.args.get("limit", 50)), 200)
    try:
        from src.mission_builder.locations import query_places_from_db
        rows = query_places_from_db(district=district, place_type=place_type, limit=limit)
        return jsonify({"places": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"places": [], "count": 0, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/image-refs — image reference library
# ---------------------------------------------------------------------------

@app.route("/api/image-refs")
def api_image_refs():
    try:
        from src.db_api import raw_query
        entity_type = request.args.get("type")
        limit = min(int(request.args.get("limit", 100)), 500)
        if entity_type:
            rows = raw_query(
                "SELECT entity_type, entity_name, image_path, ref_count, "
                "COALESCE(updated_at, created_at) AS updated_at FROM image_refs "
                "WHERE entity_type = %s ORDER BY COALESCE(updated_at, created_at) DESC LIMIT %s",
                (entity_type, limit),
            ) or []
        else:
            rows = raw_query(
                "SELECT entity_type, entity_name, image_path, ref_count, "
                "COALESCE(updated_at, created_at) AS updated_at FROM image_refs "
                "ORDER BY COALESCE(updated_at, created_at) DESC LIMIT %s",
                (limit,),
            ) or []
        for r in rows:
            r["updated_at"] = str(r.get("updated_at", ""))
            category = (
                "npcs_alt" if r.get("entity_type") == "npc_portrait_alt"
                else "npcs" if r.get("entity_type") in {"npc_portrait", "npc_portrait_action"}
                else "locations"
            )
            versions = _ref_images(category, r.get("entity_name"), r.get("image_path"))
            ref = _latest_ref_image(category, r.get("entity_name"), r.get("image_path"))
            r["image_url"] = ref.get("url", "")
            r["image_missing"] = ref.get("missing", False)
            r["versions"] = [
                {
                    "index": idx,
                    "url": version.get("url", ""),
                    "image_url": version.get("url", ""),
                    "ref_path": version.get("ref_path", ""),
                    "updated_at": str(version.get("updated_at", "")),
                    "is_latest": idx == 1,
                }
                for idx, version in enumerate(versions, start=1)
            ]
            r["version_count"] = len(r["versions"])
        return jsonify({"image_refs": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"image_refs": [], "count": 0, "error": str(e)})


_MEDIA_ALLOWED_ROOTS = [
    PROJECT_ROOT / "campaign_docs" / "image_refs",
    PROJECT_ROOT / "campaign_docs" / "battle_maps",
    PROJECT_ROOT / "campaign_docs" / "npc_appearances",
    PROJECT_ROOT / "generated_modules",
]
_MEDIA_ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".pdf", ".html", ".css", ".js", ".json"}


@app.route("/media/project/<path:filename>")
def serve_project_media(filename: str):
    """Serve generated project media from approved media directories only."""
    full = (PROJECT_ROOT / filename).resolve()
    # Must stay inside an explicitly approved media root
    if not any(_path_within(full, root) for root in _MEDIA_ALLOWED_ROOTS):
        return "Access denied", 403
    # Deny dotfiles regardless of directory
    if any(part.startswith(".") for part in full.parts):
        return "Access denied", 403
    if full.suffix.lower() not in _MEDIA_ALLOWED_EXTS:
        return "Access denied", 403
    if not full.exists() or not full.is_file():
        return "Media not found", 404
    return send_from_directory(str(full.parent), full.name)


# ---------------------------------------------------------------------------
# /api/logs — recent bot log lines
# ---------------------------------------------------------------------------

@app.route("/api/logs")
def api_logs():
    try:
        limit = min(int(request.args.get("limit", 200)), 1000)
        _HTTP_OK_RE = re.compile(r'"(?:GET|POST|PUT|DELETE|HEAD|OPTIONS) [^"]+" 2\d\d ')
        for fname in ("bot_stderr.log", "journal.txt", "dashboard_stderr.log"):
            log_file = PROJECT_ROOT / "logs" / fname
            if log_file.exists():
                raw_lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                lines = [_ANSI_RE.sub("", l) for l in raw_lines
                         if not _HTTP_OK_RE.search(l)]
                return jsonify({"lines": lines[-limit:], "total": len(lines), "file": fname})
        return jsonify({"lines": [], "total": 0, "file": "none"})
    except Exception as e:
        return jsonify({"lines": [], "error": str(e)})


# ---------------------------------------------------------------------------
# /api/mission-types — narrative templates for mission types
# ---------------------------------------------------------------------------

@app.route("/api/mission-types")
def api_mission_types():
    try:
        from src.mission_board import _init_mission_type_templates
        from src.db_api import raw_query
        _init_mission_type_templates()
        rows = raw_query(
            "SELECT slug, display_name, who, what, when_hint, why, where_hint, story_frame, keywords "
            "FROM mission_type_templates ORDER BY display_name"
        ) or []
        return jsonify({"mission_types": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"mission_types": [], "count": 0, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/bounties — active bounties
# ---------------------------------------------------------------------------

@app.route("/api/bounties")
def api_bounties():
    try:
        from src.db_api import raw_query
        status = request.args.get("status", "active")
        rows = raw_query(
            "SELECT id, title, target_type, target_name, reward_ec, status, claimed_by, created_at "
            "FROM bounties WHERE status = %s ORDER BY created_at DESC LIMIT 100",
            (status,),
        ) or []
        for r in rows:
            r["created_at"] = str(r.get("created_at", ""))
        return jsonify({"bounties": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"bounties": [], "count": 0, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/arena — arena season standings and match log
# ---------------------------------------------------------------------------

@app.route("/api/arena")
def api_arena():
    try:
        import json
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT season_number, champions_json, standings_json, started_at, ended_at "
            "FROM arena_seasons ORDER BY id DESC LIMIT 1"
        ) or []
        if not rows:
            return jsonify({"fighters": [], "match_log": [], "season": 1, "match_count": 0})
        row = rows[0]
        state = row.get("champions_json") or {}
        if isinstance(state, str):
            state = json.loads(state)
        fighters = state.get("fighters", [])
        match_log = list(reversed(state.get("match_log", [])[-20:]))
        return jsonify({
            "season": state.get("season", 1),
            "match_count": state.get("match_count", 0),
            "next_match_at": state.get("next_match_at"),
            "fighters": fighters,
            "match_log": match_log,
        })
    except Exception as e:
        return jsonify({"fighters": [], "match_log": [], "season": 1, "match_count": 0, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/parties — adventurer party profiles
# ---------------------------------------------------------------------------

@app.route("/api/parties")
def api_parties():
    try:
        from src.db_api import raw_query
        rows = raw_query(
            "SELECT party_name, reputation, formed_at FROM party_profiles ORDER BY formed_at DESC LIMIT 100"
        ) or []
        for r in rows:
            r["updated_at"] = str(r.get("formed_at", ""))
        return jsonify({"parties": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"parties": [], "count": 0, "error": str(e)})


# ---------------------------------------------------------------------------
# /api/characters + /api/towerbot-world-items — web-only TowerBot wares
# ---------------------------------------------------------------------------

@app.route("/api/characters")
def api_characters():
    if _is_external() and not _pin_ok(request.args):
        return jsonify({"error": "PIN required.", "pin_required": True}), 403
    try:
        from src.towerbot_world_shop import list_player_characters_for_shop
        rows = list_player_characters_for_shop()
        return jsonify({"characters": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"characters": [], "count": 0, "error": str(e)}), 500


@app.route("/api/towerbot-world-items")
def api_towerbot_world_items():
    if _is_external() and not _pin_ok(request.args):
        return jsonify({"error": "PIN required.", "pin_required": True}), 403
    try:
        from src.towerbot_world_shop import list_active_world_items
        rows = list_active_world_items()
        return jsonify({"items": rows, "count": len(rows)})
    except Exception as e:
        return jsonify({"items": [], "count": 0, "error": str(e)}), 500


@app.route("/api/towerbot-world-items/<int:item_id>/buy", methods=["POST"])
def api_towerbot_world_item_buy(item_id: int):
    try:
        from src.towerbot_world_shop import queue_world_item_purchase
        body = request.get_json(force=True) or {}
        if _is_external() and not _pin_ok(body):
            return jsonify({"ok": False, "error": "PIN required.", "pin_required": True}), 403
        character_id = int(body.get("character_id") or 0)
        buyer_note = str(body.get("note") or "").strip()
        player_name = str(body.get("player_name") or "").strip()
        result = queue_world_item_purchase(item_id, character_id, buyer_note, player_name=player_name)
        status = 200 if result.get("ok") else 409
        return jsonify(result), status
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# /api/modules — generated mission module browser
# ---------------------------------------------------------------------------

MODULES_DIR = PROJECT_ROOT / "generated_modules"


def _module_meta(module_dir: Path) -> dict:
    """Read index.html title + faction from a module directory, or fallback to dir name."""
    meta = {"slug": module_dir.name, "files": [], "title": module_dir.name, "faction": ""}
    try:
        index = module_dir / "index.html"
        if index.exists():
            text = index.read_text(encoding="utf-8", errors="replace")
            import re as _re
            t = _re.search(r"<title>([^<]+)</title>", text)
            if t:
                meta["title"] = t.group(1).strip()
        meta["files"] = sorted(
            p.name for p in module_dir.iterdir()
            if p.is_file() and p.suffix in (".html", ".md", ".json", ".png", ".zip")
        )
        meta["has_maps"] = (module_dir / "maps").is_dir() and bool(
            list((module_dir / "maps").glob("*.png"))
        )
        meta["map_count"] = len(list((module_dir / "maps").glob("*.png"))) if meta["has_maps"] else 0
        stat = module_dir.stat()
        import datetime as _dt
        meta["generated_at"] = _dt.datetime.fromtimestamp(stat.st_mtime).isoformat()
    except Exception:
        pass
    return meta


@app.route("/api/modules")
def api_modules():
    """List all generated module directories."""
    if not MODULES_DIR.exists():
        return jsonify({"modules": [], "count": 0})
    try:
        dirs = sorted(
            [d for d in MODULES_DIR.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        modules = [_module_meta(d) for d in dirs[:50]]
        return jsonify({"modules": modules, "count": len(modules)})
    except Exception as e:
        return jsonify({"modules": [], "count": 0, "error": str(e)})


@app.route("/api/mission-maps")
def api_mission_maps():
    """Return map URLs for one or more module slugs.

    Query param: slugs=slug1,slug2,...
    Response:    {"slug1": ["/modules/slug1/maps/R01.png", ...], ...}
    """
    slugs_raw = request.args.get("slugs", "").strip()
    if not slugs_raw:
        return jsonify({})
    result = {}
    for slug in slugs_raw.split(","):
        slug = slug.strip()
        if not slug:
            continue
        maps_dir = MODULES_DIR / slug / "maps"
        if maps_dir.is_dir():
            def _map_sort_key(path: Path):
                name = path.name.lower()
                rank = 0 if ("_nice" in name or "_pretty" in name) else 1
                return (rank, name)

            result[slug] = [
                f"/modules/{slug}/maps/{p.name}"
                for p in sorted(maps_dir.glob("*.png"), key=_map_sort_key)
            ]
        else:
            result[slug] = []
    return jsonify(result)


@app.route("/modules/<slug>/")
@app.route("/modules/<slug>")
def module_index(slug: str):
    """Serve a module's index.html."""
    safe = Path(slug).name  # prevent path traversal
    module_dir = MODULES_DIR / safe
    if not module_dir.exists():
        return f"Module '{safe}' not found", 404
    index = module_dir / "index.html"
    if index.exists():
        return send_from_directory(str(module_dir), "index.html")
    # Infestation modules may only have module.html — serve it as the landing page
    fallback = module_dir / "module.html"
    if fallback.exists():
        return send_from_directory(str(module_dir), "module.html")
    return f"No index.html for module '{safe}'", 404


@app.route("/modules/<slug>/<path:filename>")
def module_file(slug: str, filename: str):
    """Serve any file within a module directory (HTML, PNG, JSON, ZIP)."""
    safe_slug = Path(slug).name
    module_dir = MODULES_DIR / safe_slug
    if not module_dir.exists():
        return f"Module '{safe_slug}' not found", 404
    # Resolve full path and confirm it stays within module_dir
    full = (module_dir / filename).resolve()
    if not _path_within(full, module_dir):
        return "Access denied", 403
    parent = full.parent
    return send_from_directory(str(parent), full.name)


# ---------------------------------------------------------------------------
# /area-maps — overhead gazetteer area maps (generated nightly by A1111)
# ---------------------------------------------------------------------------

AREA_MAPS_DIR = PROJECT_ROOT / "Webpage" / "area_maps"


@app.route("/api/area-maps")
def api_area_maps():
    """
    Return a JSON index of all generated overhead area maps.
    Response: { district_slug: [{area_slug, area_name, url}, ...], ... }
    """
    result = {}
    if AREA_MAPS_DIR.exists():
        for dist_dir in sorted(AREA_MAPS_DIR.iterdir()):
            if not dist_dir.is_dir():
                continue
            maps = []
            for png in sorted(dist_dir.glob("*.png")):
                maps.append({
                    "area_slug": png.stem,
                    "area_name": png.stem.replace("_", " ").title(),
                    "url":       f"/area-maps/{dist_dir.name}/{png.name}",
                })
            if maps:
                result[dist_dir.name] = maps
    return jsonify(result)


@app.route("/area-maps/<path:filename>")
def serve_area_map(filename: str):
    """Serve a generated area map PNG."""
    full = (AREA_MAPS_DIR / filename).resolve()
    if not _path_within(full, AREA_MAPS_DIR):
        return "Access denied", 403
    if not full.exists():
        return "Map not found", 404
    return send_from_directory(str(full.parent), full.name)


# ---------------------------------------------------------------------------
# /api/compendium — Mimir reference browser + document reader
# ---------------------------------------------------------------------------

def _mimir_run(coro, timeout: float = 8.0):
    """Run a Mimir coroutine from Flask.

    If the bot's event loop is registered, submits the work there via
    run_coroutine_threadsafe — this keeps all Mimir asyncio.Lock accesses
    on a single loop, preventing cross-loop binding errors (F-40).
    Falls back to a fresh per-request loop when the bot is not running
    (e.g., standalone dashboard mode).
    """
    import asyncio
    import concurrent.futures
    try:
        from src.mimir_client import get_bot_loop
        bot_loop = get_bot_loop()
    except Exception:
        bot_loop = None

    if bot_loop and bot_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(
            asyncio.wait_for(coro, timeout=timeout), bot_loop
        )
        try:
            return future.result(timeout=timeout + 2)
        except (concurrent.futures.TimeoutError, asyncio.TimeoutError):
            future.cancel()
            raise TimeoutError(f"Mimir call timed out after {timeout}s")

    # Fallback: standalone mode — no bot loop registered
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(coro, timeout=timeout))
    except asyncio.TimeoutError:
        raise TimeoutError(f"Mimir call timed out after {timeout}s")
    finally:
        loop.close()


@app.route("/api/compendium/search")
def api_compendium_search():
    """
    Search the Mimir SRD catalog.
    ?category=monster|item|spell|feat|race|class|background&q=<query>
    """
    category = request.args.get("category", "monster").strip().lower()
    query    = request.args.get("q", "").strip()
    limit    = min(int(request.args.get("limit", 20)), 50)

    valid = {"monster", "item", "spell", "feat", "race", "class", "background", "condition"}
    if category not in valid:
        return jsonify({"results": [], "error": f"Unknown category '{category}'"}), 400

    try:
        from src.mimir_client import get_mimir, MIMIR_CAMPAIGN_ID
        client = get_mimir()

        # Extra filter params forwarded from the UI
        level       = request.args.get("level")
        school      = request.args.get("school", "").strip()
        class_name  = request.args.get("class_name", "").strip()
        monster_type= request.args.get("monster_type", "").strip()
        cr_min      = request.args.get("cr_min")
        cr_max      = request.args.get("cr_max")
        rarity      = request.args.get("rarity", "").strip()
        item_type   = request.args.get("item_type", "").strip()
        inc_homebrew= request.args.get("include_homebrew", "true").lower() != "false"

        async def _search():
            await client.ensure_connected()
            kwargs = {"category": category, "limit": limit}
            if query:
                kwargs["name"] = query
            if level is not None:
                try: kwargs["level"] = int(level)
                except ValueError: pass
            if school:      kwargs["school"]       = school
            if class_name:  kwargs["class_name"]   = class_name
            if monster_type:kwargs["monster_type"] = monster_type
            if cr_min is not None:
                try: kwargs["cr_min"] = float(cr_min)
                except ValueError: pass
            if cr_max is not None:
                try: kwargs["cr_max"] = float(cr_max)
                except ValueError: pass
            if rarity:      kwargs["rarity"]       = rarity
            if item_type:   kwargs["item_type"]    = item_type
            if not inc_homebrew: kwargs["include_homebrew"] = False

            raw = await client._call("search_catalog", **kwargs)
            if isinstance(raw, dict):
                total = raw.get("count", 0)
                for key in (category + "s", category, "results", "items", "monsters", "spells",
                            "feats", "races", "classes", "backgrounds", "conditions"):
                    if key in raw:
                        return raw[key], total
                return list(raw.values())[0] if raw else [], total
            if isinstance(raw, list):
                return raw, len(raw)
            return [], 0

        results, total = _mimir_run(_search())
        return jsonify({"results": results or [], "count": total or len(results or [])})
    except Exception as e:
        return jsonify({"results": [], "error": str(e)}), 500


@app.route("/api/compendium/documents")
def api_compendium_documents():
    """
    List all campaign-level Mimir documents enriched with faction info.
    dm_notes docs get a 'faction' field by cross-referencing the MySQL npcs table.
    """
    try:
        from src.mimir_client import get_mimir, MIMIR_CAMPAIGN_ID
        import re as _re

        client = get_mimir()

        async def _list():
            await client.ensure_connected()
            campaign_id = client.campaign_id or MIMIR_CAMPAIGN_ID
            raw = await client._call("list_documents", campaign_id=campaign_id)
            return (raw or {}).get("documents", [])

        docs = _mimir_run(_list()) or []

        # Build NPC name→faction lookup from MySQL for dm_notes enrichment
        npc_faction: dict = {}
        try:
            from src.db_api import raw_query
            rows = raw_query("SELECT name, faction FROM npcs") or []
            _paren = _re.compile(r'\s*\([^)]*\)\s*$')
            _slash = _re.compile(r'\s*/.*$')
            def _clean_faction(f: str) -> str:
                f = (_paren.sub("", f) if f else f) or "Independent"
                # Normalise "Tower Authority / FTA" → "Tower Authority"
                f = _slash.sub("", f).strip()
                return f or "Independent"
            npc_faction = {r["name"].lower(): _clean_faction(r.get("faction") or "Independent")
                           for r in rows if r.get("name")}
        except Exception:
            pass

        _dm_suffix = _re.compile(r'\s*[—–-]\s*DM Notes\s*$', _re.IGNORECASE)
        for doc in docs:
            if doc.get("doc_type") == "dm_notes":
                raw_title = doc.get("title", "")
                npc_name  = _dm_suffix.sub("", raw_title).strip()
                doc["npc_name"] = npc_name
                faction = npc_faction.get(npc_name.lower(), "")
                if not faction:
                    # fuzzy: try first word + last word match
                    parts = npc_name.lower().split()
                    for stored_name, stored_faction in npc_faction.items():
                        stored_parts = stored_name.split()
                        if parts and stored_parts and parts[0] == stored_parts[0]:
                            faction = stored_faction
                            break
                doc["faction"] = faction or "Unknown"

        # Deduplicate faction description docs (strip [brackets], normalise slash variants)
        _bracket_re = _re.compile(r'^\[(.+)\]$')
        _slash_norm  = _re.compile(r'\s*/.*$')
        seen_faction_keys: dict = {}
        deduped: list = []
        for doc in docs:
            if doc.get("doc_type") == "description":
                raw_title = (doc.get("title") or "").strip()
                bm = _bracket_re.match(raw_title)
                display = bm.group(1).strip() if bm else raw_title
                norm_key = _slash_norm.sub("", display).strip().lower()
                if norm_key in seen_faction_keys:
                    if not bm:
                        # non-bracketed version is better — replace the stored one
                        idx = seen_faction_keys[norm_key]
                        deduped[idx] = dict(doc)
                    continue
                d2 = dict(doc)
                d2["title"] = display          # strip brackets from display name
                seen_faction_keys[norm_key] = len(deduped)
                deduped.append(d2)
            else:
                deduped.append(doc)
        docs = deduped

        # Sort order: world → factions → npc notes (by faction then name) → other
        _order = {"backstory": 0, "description": 1, "dm_notes": 2}
        docs.sort(key=lambda d: (
            _order.get(d.get("doc_type", ""), 3),
            (d.get("faction") or "").lower() if d.get("doc_type") == "dm_notes" else "",
            (d.get("npc_name") or d.get("title") or "").lower(),
        ))
        return jsonify({"documents": docs, "count": len(docs)})
    except Exception as e:
        return jsonify({"documents": [], "error": str(e)}), 500


@app.route("/api/compendium/document/<doc_id>")
def api_compendium_document(doc_id: str):
    """Read a single Mimir document by ID."""
    try:
        from src.mimir_client import get_mimir
        client = get_mimir()

        async def _read():
            await client.ensure_connected()
            raw = await client._call("read_document", document_id=doc_id)
            return (raw or {}).get("document", raw)

        doc = _mimir_run(_read())
        if not doc:
            return jsonify({"error": "Document not found"}), 404
        return jsonify({"document": doc})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("DASHBOARD_PORT", 5000))
    debug = os.getenv("FLASK_DEBUG", "false").lower() == "true"
    print(f"TowerBot Dashboard -> http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
