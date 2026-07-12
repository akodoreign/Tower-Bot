"""
session_runner.py — Generate a tablet-optimised interactive session runner HTML page.

Extracts scenes, read-aloud text and NPC names from the rendered module HTML,
then writes a self-contained session.html with:
  - Scene checklist (tap to mark complete)
  - Read-aloud viewer (tap scene → read the box aloud)
  - Initiative / HP tracker (add any combatant, track HP live)
  - Running notes (auto-saved to localStorage)
  - Debrief form (submits to /api/complete-mission)

All state (checked scenes, HP, initiative order, notes) is kept in localStorage
so a page refresh never loses progress mid-session.
"""

from __future__ import annotations

import re
import json
import os
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Scene extraction from rendered module.html
# ---------------------------------------------------------------------------

def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html).strip()


def extract_scenes(module_html_path: Path) -> list[dict]:
    """
    Parse Scene N headings + read-aloud + NPC names from module.html.
    Returns list of {id, title, read_aloud, npcs, location}.
    """
    if not module_html_path.exists():
        return []

    text = module_html_path.read_text(encoding="utf-8", errors="replace")

    # Split on Scene headings
    pattern = re.compile(
        r"<h[34][^>]*>(Scene\s+\d+[^<]*)</h[34]>(.*?)(?=<h[34][^>]*>Scene\s+\d+|<h2|</body>)",
        re.DOTALL | re.IGNORECASE,
    )

    scenes = []
    for m in pattern.finditer(text):
        raw_title = _strip_tags(m.group(1)).strip()
        body = m.group(2)

        # Read-aloud block
        ra_m = re.search(
            r'class="read-aloud[^"]*">(.*?)</div>', body, re.DOTALL | re.IGNORECASE
        )
        read_aloud = _strip_tags(ra_m.group(1)).strip() if ra_m else ""
        # Strip "📖 Read Aloud to Players" prefix if present
        read_aloud = re.sub(r"^📖\s*Read\s+Aloud\s+to\s+Players\s*", "", read_aloud).strip()

        # NPC names from "NPCs Present" section — grab <li> items or plain lines
        npc_section = re.search(
            r"NPCs?\s+Present</h[3-6]>(.*?)(?=<h[3-6]|$)",
            body, re.DOTALL | re.IGNORECASE,
        )
        npc_names: list[str] = []
        if npc_section:
            npc_html = npc_section.group(1)
            # Prefer <li> items (most common format)
            items = re.findall(r"<li[^>]*>(.*?)</li>", npc_html, re.DOTALL)
            for item in items:
                raw = _strip_tags(item).strip().split(" - ")[0].split("—")[0].strip()
                # NPC names are typically Title Case, under 50 chars
                if 2 < len(raw) < 50 and not raw.startswith(("DC", "If ", "The ")):
                    npc_names.append(raw)
            # Fallback: plain text lines if no <li> items
            if not npc_names:
                for line in _strip_tags(npc_html).splitlines():
                    line = line.strip().lstrip("-•·*").strip().split(" - ")[0].strip()
                    if 2 < len(line) < 50:
                        npc_names.append(line)

        # Location hint from title or body
        loc_m = re.search(r"(?:Location|Setting|Place)[:\s]+([^\n]{5,60})", body, re.IGNORECASE)
        location = loc_m.group(1).strip() if loc_m else ""

        slug = re.sub(r"[^a-z0-9]+", "_", raw_title.lower()).strip("_")
        scenes.append({
            "id":         slug,
            "title":      raw_title,
            "read_aloud": read_aloud,
            "npcs":       npc_names[:6],
            "location":   location,
        })

    if not scenes:
        import logging as _log
        _log.getLogger(__name__).info(
            f"extract_scenes: no Scene N headings found in {module_html_path.name} "
            f"({len(text)} chars) — session runner will have no scenes"
        )
    return scenes


def extract_module_meta(module_html_path: Path) -> dict:
    """Pull mission title, faction and reward from module.html."""
    if not module_html_path.exists():
        return {}
    text = module_html_path.read_text(encoding="utf-8", errors="replace")
    title_m = re.search(r"<title>([^<]+)</title>", text)
    h1_m    = re.search(r"<h1[^>]*>([^<]+)</h1>", text)
    title   = _strip_tags(title_m.group(1) if title_m else (h1_m.group(1) if h1_m else "Mission"))
    # Strip " — Module" suffix added by render_component
    title   = re.sub(r"\s*[—–-]\s*Module$", "", title).strip()
    return {"title": title}


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_DASHBOARD_PORT = os.getenv("DASHBOARD_PORT", "5001")


def generate_session_html(
    out_dir: Path,
    mission_title: str,
    faction: str,
    tier: str,
    player_name: str,
    mission_id: Optional[int] = None,
    scenes: Optional[list[dict]] = None,
) -> Path:
    """
    Write session.html into out_dir.
    Returns the path to the written file.
    """
    scenes = scenes or []
    scenes_json = json.dumps(scenes, ensure_ascii=False)

    # Build scene cards HTML (static — JS drives interactivity)
    scene_cards = ""
    for i, sc in enumerate(scenes):
        npcs_html = ""
        for npc in sc.get("npcs", []):
            npcs_html += f'<span class="npc-chip" onclick="addCombatant(this)" data-name="{npc}">{npc} +</span>'

        ra = sc.get("read_aloud", "").replace('"', "&quot;").replace("<", "&lt;")
        scene_cards += f"""
<div class="scene-card" id="sc-{sc['id']}" data-scene="{i}">
  <div class="scene-header" onclick="toggleScene({i})">
    <label class="check-wrap" onclick="event.stopPropagation()">
      <input type="checkbox" id="chk-{i}" onchange="markScene({i})">
      <span class="checkmark"></span>
    </label>
    <span class="scene-title">{sc['title']}</span>
    <span class="scene-chevron" id="chev-{i}">▼</span>
  </div>
  <div class="scene-body" id="body-{i}" style="display:none;">
    {'<div class="ra-box"><div class="ra-label">📖 Read Aloud</div><div class="ra-text">' + ra + '</div></div>' if ra else ''}
    {'<div class="npc-row"><span class="npc-label">NPCs → initiative:</span>' + npcs_html + '</div>' if npcs_html else ''}
    {'<div class="loc-line">📍 ' + sc['location'] + '</div>' if sc.get('location') else ''}
  </div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<title>▶ {mission_title} — Session</title>
<style>
/* ── Reset & base ──────────────────────────────────────────────────── */
*{{ box-sizing:border-box; margin:0; padding:0; -webkit-tap-highlight-color:transparent; }}
:root{{
  --ink:      #1a1208;
  --parch:    #fdf8f0;
  --gold:     #b8923a;
  --gold-lt:  #e8c87a;
  --ember:    #c85320;
  --green:    #3a7a3a;
  --red:      #9a2020;
  --panel:    #f5f0e4;
  --border:   rgba(26,18,8,.15);
  --shadow:   0 2px 8px rgba(26,18,8,.12);
  --r:        10px;
  --touch:    52px;
}}
html,body{{ height:100%; font-family:'Georgia',serif; background:var(--parch); color:var(--ink); font-size:16px; }}

/* ── Top nav ───────────────────────────────────────────────────────── */
.top-nav{{
  position:sticky; top:0; z-index:100;
  background:var(--ink); border-bottom:2px solid var(--gold);
  padding:10px 16px; display:flex; align-items:center; gap:16px;
}}
.top-nav a{{ color:var(--gold-lt); text-decoration:none; font-size:14px; white-space:nowrap; }}
.top-nav a:hover{{ color:white; }}
.nav-title{{ color:var(--gold-lt); font-size:15px; font-weight:bold; flex:1; text-align:center;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.nav-sub{{ color:rgba(232,200,122,.6); font-size:11px; font-style:italic; }}

/* ── Tab bar ───────────────────────────────────────────────────────── */
.tab-bar{{
  display:flex; background:var(--ink); border-bottom:1px solid rgba(184,146,58,.3);
  overflow-x:auto; scrollbar-width:none;
}}
.tab-bar::-webkit-scrollbar{{ display:none; }}
.tab-btn{{
  flex:none; padding:12px 20px; color:rgba(232,200,122,.6);
  font-size:13px; cursor:pointer; border:none; background:none;
  border-bottom:2px solid transparent; font-family:inherit; white-space:nowrap;
  transition:.15s;
}}
.tab-btn.on{{ color:var(--gold-lt); border-bottom-color:var(--ember); }}

/* ── Section wrapper ───────────────────────────────────────────────── */
.section{{ display:none; padding:16px; max-width:860px; margin:0 auto; }}
.section.on{{ display:block; }}

/* ── Scene cards ───────────────────────────────────────────────────── */
.scene-card{{
  background:var(--panel); border:1px solid var(--border); border-radius:var(--r);
  margin-bottom:12px; overflow:hidden; transition:.2s;
}}
.scene-card.done{{ opacity:.55; }}
.scene-header{{
  display:flex; align-items:center; gap:12px;
  padding:14px 16px; cursor:pointer; min-height:var(--touch);
}}
.scene-title{{ font-size:15px; font-weight:bold; flex:1; }}
.scene-chevron{{ color:var(--gold); font-size:12px; transition:.2s; }}
.scene-body{{ padding:0 16px 16px; border-top:1px solid var(--border); }}

/* Checkbox */
.check-wrap{{ position:relative; width:28px; height:28px; flex:none; cursor:pointer; }}
.check-wrap input{{ opacity:0; width:0; height:0; position:absolute; }}
.checkmark{{
  position:absolute; inset:0; border-radius:6px;
  border:2px solid var(--gold); background:white;
  display:flex; align-items:center; justify-content:center;
}}
.check-wrap input:checked + .checkmark{{
  background:var(--green); border-color:var(--green);
}}
.check-wrap input:checked + .checkmark::after{{
  content:"✓"; color:white; font-size:16px; font-weight:bold;
}}

/* Read-aloud box */
.ra-box{{
  background:#fffbf0; border-left:4px solid var(--gold);
  border-radius:0 6px 6px 0; padding:14px 16px; margin:14px 0;
}}
.ra-label{{ font-size:11px; text-transform:uppercase; letter-spacing:.1em;
  color:var(--gold); font-weight:bold; margin-bottom:8px; }}
.ra-text{{ font-size:15px; line-height:1.65; font-style:italic; }}

/* NPC chips */
.npc-row{{ display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; align-items:center; }}
.npc-label{{ font-size:12px; color:#666; margin-right:4px; }}
.npc-chip{{
  background:var(--ink); color:var(--gold-lt); border-radius:20px;
  padding:6px 14px; font-size:13px; cursor:pointer; user-select:none;
  transition:.15s;
}}
.npc-chip:hover{{ background:#3a2a10; }}
.loc-line{{ margin-top:10px; font-size:13px; color:#666; }}

/* ── Initiative tracker ────────────────────────────────────────────── */
.init-toolbar{{ display:flex; gap:8px; margin-bottom:14px; flex-wrap:wrap; }}
.init-toolbar input{{
  flex:1; min-width:120px; border:1px solid var(--border); border-radius:8px;
  padding:10px 14px; font-size:15px; font-family:inherit;
  background:white; color:var(--ink);
}}
.btn{{
  padding:10px 18px; border:none; border-radius:8px; font-size:14px;
  cursor:pointer; font-family:inherit; font-weight:bold; transition:.15s;
  min-height:var(--touch);
}}
.btn-gold{{ background:var(--gold); color:white; }}
.btn-gold:hover{{ background:#a07828; }}
.btn-sm{{ padding:6px 12px; font-size:13px; border-radius:6px; min-height:36px; }}
.btn-red{{ background:var(--red); color:white; }}
.btn-green{{ background:var(--green); color:white; }}
.btn-ghost{{ background:rgba(26,18,8,.07); color:var(--ink); }}

#combatants{{ display:flex; flex-direction:column; gap:8px; }}
.combatant{{
  background:white; border:1px solid var(--border); border-radius:var(--r);
  padding:12px 14px; display:flex; align-items:center; gap:12px;
}}
.combatant.active{{ border-left:4px solid var(--ember); background:#fff8f4; }}
.combatant.dead{{ opacity:.4; text-decoration:line-through; }}
.c-turn{{ font-size:20px; font-weight:bold; color:var(--gold); width:28px; text-align:center; flex:none; }}
.c-name{{ flex:1; font-size:15px; font-weight:bold; }}
.c-hp-wrap{{ display:flex; align-items:center; gap:6px; flex:none; }}
.c-hp{{
  width:54px; text-align:center; border:1px solid var(--border); border-radius:6px;
  padding:6px; font-size:16px; font-weight:bold; font-family:inherit;
  background:var(--panel);
}}
.c-hp.low{{ color:var(--red); border-color:var(--red); }}
.c-hp.zero{{ color:var(--red); border-color:var(--red); background:#fff0f0; }}
.c-btns{{ display:flex; gap:4px; flex:none; }}
.init-number{{
  width:44px; text-align:center; border:1px solid var(--border); border-radius:6px;
  padding:6px; font-size:14px; font-family:inherit; background:white;
}}
.turn-controls{{ display:flex; gap:8px; margin-top:12px; }}

/* ── Notes ─────────────────────────────────────────────────────────── */
.notes-area{{
  width:100%; min-height:260px; border:1px solid var(--border); border-radius:var(--r);
  padding:16px; font-size:15px; font-family:'Georgia',serif; line-height:1.6;
  background:white; resize:vertical;
}}

/* ── Debrief form ──────────────────────────────────────────────────── */
.debrief-section h2{{ font-size:20px; margin-bottom:6px; }}
.debrief-section p{{ font-size:14px; color:#555; margin-bottom:18px; }}
.field-group{{ margin-bottom:18px; }}
.field-label{{
  display:block; font-size:12px; text-transform:uppercase; letter-spacing:.12em;
  font-weight:bold; color:#666; margin-bottom:6px;
}}
.field-input, .field-textarea{{
  width:100%; border:1px solid var(--border); border-radius:8px;
  padding:12px 14px; font-size:15px; font-family:'Georgia',serif;
  background:white; color:var(--ink);
}}
.field-textarea{{ min-height:90px; resize:vertical; }}
.submit-row{{ margin-top:24px; display:flex; gap:12px; flex-wrap:wrap; }}
.result-box{{
  margin-top:16px; padding:14px; border-radius:var(--r);
  font-size:14px; display:none;
}}
.result-box.ok{{ background:#e8f5e8; border:1px solid #4a8a4a; color:#1a4a1a; }}
.result-box.err{{ background:#fde8e8; border:1px solid #c04040; color:#6a0000; }}

/* ── Progress bar at top of scenes ────────────────────────────────── */
.progress-bar-wrap{{ background:rgba(26,18,8,.08); border-radius:4px; height:6px; margin-bottom:16px; overflow:hidden; }}
.progress-bar-fill{{ height:100%; background:var(--green); border-radius:4px; transition:.4s; }}
.progress-label{{ font-size:12px; color:#888; margin-bottom:6px; }}

@media(max-width:600px){{
  .section{{ padding:12px; }}
  .top-nav{{ padding:8px 12px; }}
  .nav-title{{ font-size:13px; }}
}}
</style>
</head>
<body>

<nav class="top-nav">
  <a href="/">⬅ Dashboard</a>
  <a href="index.html">◀ Index</a>
  <div class="nav-title">
    {mission_title}
    <div class="nav-sub">{faction} · {tier}</div>
  </div>
</nav>

<div class="tab-bar">
  <button class="tab-btn on" onclick="showTab('scenes')">📋 Scenes</button>
  <button class="tab-btn"    onclick="showTab('combat')">⚔️ Combat</button>
  <button class="tab-btn"    onclick="showTab('notes')">📝 Notes</button>
  <button class="tab-btn"    onclick="showTab('debrief')">✅ Debrief</button>
</div>

<!-- ── SCENES ──────────────────────────────────────────────────────── -->
<div class="section on" id="sec-scenes">
  <div class="progress-label" id="prog-label">0 of {len(scenes)} scenes complete</div>
  <div class="progress-bar-wrap"><div class="progress-bar-fill" id="prog-bar" style="width:0%"></div></div>
  {scene_cards if scene_cards else '<p style="color:#888;padding:20px 0;">No scenes found — open the module for the full adventure text.</p>'}
</div>

<!-- ── COMBAT ──────────────────────────────────────────────────────── -->
<div class="section" id="sec-combat">
  <div class="init-toolbar">
    <input type="text"   id="c-name" placeholder="Name (e.g. Goblin 1)" maxlength="40">
    <input type="number" id="c-init" placeholder="Init" min="1" max="30" style="width:74px;flex:none;">
    <input type="number" id="c-hp"   placeholder="HP"   min="1" max="999" style="width:74px;flex:none;">
    <input type="number" id="c-ac"   placeholder="AC"   min="1" max="30"  style="width:74px;flex:none;">
    <button class="btn btn-gold" onclick="addCombatantManual()">+ Add</button>
  </div>
  <div id="combatants"></div>
  <div class="turn-controls" id="turn-controls" style="display:none;">
    <button class="btn btn-ghost" onclick="nextTurn()">▶ Next Turn</button>
    <button class="btn btn-ghost btn-sm" onclick="resetCombat()">↺ Reset Round</button>
    <button class="btn btn-red btn-sm" onclick="clearCombat()">✕ End Combat</button>
  </div>
</div>

<!-- ── NOTES ───────────────────────────────────────────────────────── -->
<div class="section" id="sec-notes">
  <p style="font-size:13px;color:#888;margin-bottom:10px;">
    Auto-saved to this device. Won't survive clearing browser data.
  </p>
  <textarea class="notes-area" id="session-notes"
    placeholder="Session notes, player decisions, things to remember...&#10;&#10;This auto-saves as you type."
    oninput="saveNotes()"></textarea>
</div>

<!-- ── DEBRIEF ─────────────────────────────────────────────────────── -->
<div class="section debrief-section" id="sec-debrief">
  <h2>Mission Debrief</h2>
  <p>Fill this in at the end of the session. Submits directly to the dashboard — no Discord needed.</p>

  <div class="field-group">
    <label class="field-label" for="db-by">Completed by (party / player name)</label>
    <input type="text" id="db-by" class="field-input" value="{player_name}" placeholder="Party name">
  </div>
  <div class="field-group">
    <label class="field-label" for="db-result">Result</label>
    <select id="db-result" class="field-input" style="cursor:pointer;">
      <option value="completed">✅ Completed</option>
      <option value="failed">💥 Failed</option>
    </select>
  </div>
  <div class="field-group">
    <label class="field-label" for="db-killed">NPCs killed or major consequences</label>
    <textarea id="db-killed" class="field-textarea"
      placeholder="Names of NPCs killed, locations destroyed, or 'None'"></textarea>
  </div>
  <div class="field-group">
    <label class="field-label" for="db-decisions">Key decisions made</label>
    <textarea id="db-decisions" class="field-textarea"
      placeholder="Choices that shaped the outcome, alliances made or broken..."></textarea>
  </div>
  <div class="field-group">
    <label class="field-label" for="db-changes">Location / world changes</label>
    <textarea id="db-changes" class="field-textarea"
      placeholder="Places destroyed, NPCs moved, factions affected..."></textarea>
  </div>
  <div class="field-group">
    <label class="field-label" for="db-threads">Loose threads to follow up</label>
    <textarea id="db-threads" class="field-textarea"
      placeholder="Unresolved leads, enemies who escaped, questions raised..."></textarea>
  </div>
  <div class="field-group">
    <label class="field-label" for="db-moments">Notable moments</label>
    <textarea id="db-moments" class="field-textarea"
      placeholder="Memorable plays, dramatic turns, things to celebrate..."></textarea>
  </div>

  <div class="submit-row">
    <button class="btn btn-gold" onclick="submitDebrief()" style="font-size:16px;padding:14px 28px;">
      Submit to Dashboard ↗
    </button>
    <button class="btn btn-ghost" onclick="saveDebriefDraft()">Save draft locally</button>
  </div>
  <div class="result-box" id="debrief-result"></div>
</div>

<script>
/* ── Constants ─────────────────────────────────────────────────────── */
const MISSION_TITLE = {json.dumps(mission_title)};
const MISSION_ID    = {json.dumps(mission_id)};
const STORAGE_KEY   = "session_" + MISSION_TITLE.replace(/[^a-z0-9]/gi,"_").toLowerCase();
const SCENES        = {scenes_json};

/* ── Tab routing ───────────────────────────────────────────────────── */
function showTab(name) {{
  document.querySelectorAll(".section").forEach(s => s.classList.remove("on"));
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("on"));
  document.getElementById("sec-" + name).classList.add("on");
  event.currentTarget.classList.add("on");
}}

/* ── Scene checklist ───────────────────────────────────────────────── */
function toggleScene(i) {{
  const body = document.getElementById("body-"+i);
  const chev = document.getElementById("chev-"+i);
  const open = body.style.display === "none";
  body.style.display = open ? "block" : "none";
  chev.textContent = open ? "▲" : "▼";
}}

function markScene(i) {{
  const chk = document.getElementById("chk-"+i);
  const card = document.querySelector(`[data-scene="${{i}}"]`);
  card.classList.toggle("done", chk.checked);
  saveState();
  updateProgress();
}}

function updateProgress() {{
  const total = SCENES.length;
  if (!total) return;
  const done = document.querySelectorAll(".scene-card.done").length;
  document.getElementById("prog-label").textContent =
    done + " of " + total + " scene" + (total!==1?"s":"") + " complete";
  document.getElementById("prog-bar").style.width = Math.round(100*done/total) + "%";
}}

/* ── Initiative / HP tracker ───────────────────────────────────────── */
let combatants = [];
let currentTurn = 0;

function addCombatant(chipEl) {{
  const name = chipEl.dataset.name;
  const hp   = parseInt(prompt("HP for " + name + "?", "10")) || 10;
  const init = parseInt(prompt("Initiative roll for " + name + "?", "10")) || 10;
  _pushCombatant({{ name, init, hp, maxHp:hp, ac:10, id: Date.now() }});
}}

function addCombatantManual() {{
  const name = document.getElementById("c-name").value.trim();
  if (!name) {{ document.getElementById("c-name").focus(); return; }}
  const init = parseInt(document.getElementById("c-init").value) || 10;
  const hp   = parseInt(document.getElementById("c-hp").value)   || 10;
  const ac   = parseInt(document.getElementById("c-ac").value)   || 10;
  _pushCombatant({{ name, init, hp, maxHp:hp, ac, id:Date.now() }});
  document.getElementById("c-name").value = "";
  document.getElementById("c-init").value = "";
  document.getElementById("c-hp").value   = "";
  document.getElementById("c-ac").value   = "";
  document.getElementById("c-name").focus();
}}

function _pushCombatant(c) {{
  combatants.push(c);
  combatants.sort((a,b) => b.init - a.init);
  renderCombat();
  saveState();
}}

function renderCombat() {{
  const el = document.getElementById("combatants");
  const tc = document.getElementById("turn-controls");
  tc.style.display = combatants.length ? "flex" : "none";

  el.innerHTML = combatants.map((c, i) => {{
    const hpClass = c.hp <= 0 ? "zero" : (c.hp < c.maxHp * 0.3 ? "low" : "");
    const dead    = c.hp <= 0 ? " dead" : "";
    const active  = i === currentTurn ? " active" : "";
    return `
<div class="combatant${{active}}${{dead}}" id="cb-${{c.id}}">
  <span class="c-turn">${{i===currentTurn ? "▶" : i+1}}</span>
  <span class="c-name">${{c.name}}</span>
  <span style="font-size:12px;color:#888;">AC ${{c.ac}}</span>
  <div class="c-hp-wrap">
    <button class="btn btn-red btn-sm" onclick="dmgHeal(${{i}},-1)" style="width:36px;">-</button>
    <input type="number" class="c-hp ${{hpClass}}" value="${{c.hp}}" min="0" max="${{c.maxHp+50}}"
      onchange="setHp(${{i}},this.value)">
    <span style="font-size:11px;color:#aaa;">/${{c.maxHp}}</span>
    <button class="btn btn-green btn-sm" onclick="dmgHeal(${{i}},1)" style="width:36px;">+</button>
  </div>
  <button class="btn btn-ghost btn-sm" onclick="removeCombatant(${{i}})" style="width:36px;">✕</button>
</div>`;
  }}).join("");
}}

function dmgHeal(i, dir) {{
  const amt = parseInt(prompt(dir>0?"Heal how much?":"Damage how much?","5")) || 0;
  combatants[i].hp = Math.max(0, Math.min(combatants[i].maxHp + 50, combatants[i].hp + dir*amt));
  renderCombat(); saveState();
}}
function setHp(i, val) {{
  combatants[i].hp = Math.max(0, parseInt(val)||0);
  renderCombat(); saveState();
}}
function removeCombatant(i) {{
  combatants.splice(i, 1);
  if (currentTurn >= combatants.length) currentTurn = 0;
  renderCombat(); saveState();
}}
function nextTurn() {{
  if (!combatants.length) return;
  currentTurn = (currentTurn + 1) % combatants.length;
  renderCombat(); saveState();
}}
function resetCombat() {{
  currentTurn = 0;
  renderCombat(); saveState();
}}
function clearCombat() {{
  if (!confirm("Clear all combatants?")) return;
  combatants = []; currentTurn = 0;
  renderCombat(); saveState();
}}

/* ── Notes auto-save ───────────────────────────────────────────────── */
let _noteTimer;
function saveNotes() {{
  clearTimeout(_noteTimer);
  _noteTimer = setTimeout(() => {{
    const st = loadState();
    st.notes = document.getElementById("session-notes").value;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(st));
  }}, 600);
}}

/* ── Persist state ─────────────────────────────────────────────────── */
function loadState() {{
  try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}"); }}
  catch {{ return {{}}; }}
}}

function saveState() {{
  const st = loadState();
  st.scenes     = SCENES.map((_, i) => document.getElementById("chk-"+i)?.checked || false);
  st.combatants = combatants;
  st.turn       = currentTurn;
  st.notes      = document.getElementById("session-notes")?.value || st.notes || "";
  localStorage.setItem(STORAGE_KEY, JSON.stringify(st));
}}

function restoreState() {{
  const st = loadState();
  // Scenes
  (st.scenes || []).forEach((done, i) => {{
    const chk  = document.getElementById("chk-"+i);
    const card = document.querySelector(`[data-scene="${{i}}"]`);
    if (chk && done) {{ chk.checked = true; card?.classList.add("done"); }}
  }});
  updateProgress();
  // Combat
  combatants   = st.combatants || [];
  currentTurn  = st.turn       || 0;
  renderCombat();
  // Notes
  const ta = document.getElementById("session-notes");
  if (ta && st.notes) ta.value = st.notes;
  // Debrief draft
  if (st.debrief) {{
    const d = st.debrief;
    ["by","result","killed","decisions","changes","threads","moments"].forEach(k => {{
      const el = document.getElementById("db-"+k);
      if (el && d[k] !== undefined) el.value = d[k];
    }});
  }}
}}

/* ── Debrief submission ─────────────────────────────────────────────── */
function saveDebriefDraft() {{
  const st = loadState();
  st.debrief = debriefData();
  localStorage.setItem(STORAGE_KEY, JSON.stringify(st));
  showResult("Draft saved to this device.", true);
}}

function debriefData() {{
  return {{
    by:        document.getElementById("db-by").value.trim(),
    result:    document.getElementById("db-result").value,
    killed:    document.getElementById("db-killed").value.trim(),
    decisions: document.getElementById("db-decisions").value.trim(),
    changes:   document.getElementById("db-changes").value.trim(),
    threads:   document.getElementById("db-threads").value.trim(),
    moments:   document.getElementById("db-moments").value.trim(),
  }};
}}

async function submitDebrief() {{
  const d = debriefData();
  const btn = document.querySelector("[onclick='submitDebrief()']");
  btn.disabled = true;
  btn.textContent = "Submitting…";
  try {{
    const resp = await fetch("/api/complete-mission", {{
      method:  "POST",
      headers: {{"Content-Type":"application/json"}},
      body:    JSON.stringify({{
        mission_title:    MISSION_TITLE,
        mission_id:       MISSION_ID,
        completed_by:     d.by,
        result:           d.result,
        npcs_killed:      d.killed,
        key_decisions:    d.decisions,
        location_changes: d.changes,
        loose_threads:    d.threads,
        notable_moments:  d.moments,
      }}),
    }});
    const json = await resp.json();
    if (json.ok) {{
      showResult("✅ Submitted! Mission marked " + d.result + " on the dashboard.", true);
      btn.textContent = "Submitted ✓";
    }} else {{
      showResult("❌ Error: " + (json.error || "Unknown error"), false);
      btn.disabled = false; btn.textContent = "Submit to Dashboard ↗";
    }}
  }} catch(e) {{
    showResult("❌ Could not reach dashboard. Are you connected? (" + e.message + ")", false);
    btn.disabled = false; btn.textContent = "Submit to Dashboard ↗";
  }}
}}

function showResult(msg, ok) {{
  const el = document.getElementById("debrief-result");
  el.textContent = msg;
  el.className = "result-box " + (ok ? "ok" : "err");
  el.style.display = "block";
  el.scrollIntoView({{behavior:"smooth", block:"nearest"}});
}}

/* ── Boot ──────────────────────────────────────────────────────────── */
restoreState();
</script>
</body>
</html>"""

    out_path = out_dir / "session.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path
