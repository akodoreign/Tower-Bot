---
name: stepped-operations
description: Logged stepped operations with checkpoint/resume support. Use this skill for ANY multi-step task that could be interrupted (batch edits, large file operations, data migrations, multiple NPC updates, document generation). CRITICAL - when user says 'retry', 'continue', 'pick up where you left off', or 'got cut off', this means RESUME from the last completed step, NOT start over. Always create worklogs, track progress, and design operations to be idempotent and resumable.
---

# Stepped Operations — Session Continuity Skill

## CORE PRINCIPLE

**Every multi-step operation must be resumable.** Context windows get cut off. Sessions end unexpectedly. The user should never have to re-explain work that was already done.

---

## When This Skill Applies

Use this pattern for:
- Batch NPC roster updates (adding multiple NPCs)
- Multi-file edits across the codebase
- Data migrations or JSON restructuring
- Document generation with multiple sections
- Any task with 3+ distinct steps
- Anything the user might say "continue" about later

---

## The Worklog Pattern

### Create a Worklog First

Before starting any multi-step operation, create a worklog file:

**Location:** `C:\Users\akodoreign\Desktop\chatGPT-discord-bot\logs\worklog_[task-name].md`

**Template:**
```markdown
# Worklog: [Task Name]
**Started:** [timestamp]
**Status:** IN PROGRESS | COMPLETED | BLOCKED

## Task Summary
[1-2 sentence description of what we're doing]

## Steps
- [ ] Step 1: [description]
- [ ] Step 2: [description]
- [ ] Step 3: [description]

## Progress Log
### [timestamp]
- Completed: [what was done]
- Next: [what comes next]
- Blockers: [any issues]

## Checkpoint Data
[Any data needed to resume — IDs, partial results, intermediate state]
```

### Update the Worklog After Each Step

After completing each step:
1. Mark the step complete: `- [x] Step 1: ...`
2. Add a progress log entry
3. Record any checkpoint data needed to resume

---

## Resume Protocol

When the user says "continue", "retry", "pick up where you left off", "got cut off", or similar:

1. **DO NOT START OVER**
2. Check for existing worklogs in `C:\Users\akodoreign\Desktop\chatGPT-discord-bot\logs\`
3. Read the most recent relevant worklog
4. Find the last completed step
5. Resume from the next uncompleted step
6. Tell the user: "Resuming from step N — [description]"

**Example response:**
> "I found the worklog from our previous session. You completed steps 1-5 (adding 5 faction leaders to the roster). Resuming from step 6: adding Mari Fen (Adventurers Guild)."

---

## Idempotent Operations

Design operations to be **idempotent** — running them twice should not cause problems.

**Bad (not idempotent):**
```python
# Appends every time — duplicates if run twice
roster.append(new_npc)
```

**Good (idempotent):**
```python
# Check first, only add if missing
if not any(npc["name"] == new_npc["name"] for npc in roster):
    roster.append(new_npc)
```

---

## Checkpoint Data Examples

### For NPC Roster Merges
```markdown
## Checkpoint Data
NPCs already added: Serrik Dhal, Lady Cerys Valemont, High Apostle Yzura
NPCs remaining: The Widow, Senior Archivist Pell, Mari Fen, Eir Velan, Director Myra Kess, Brother Thane
Current roster count: 73
```

### For Multi-File Edits
```markdown
## Checkpoint Data
Files modified: src/news_feed.py, src/mission_board.py
Files remaining: src/self_learning.py, src/npc_lifecycle.py
Last edit: Added RIFT_BAN constant to mission_board.py line 142
```

### For Document Generation
```markdown
## Checkpoint Data
Sections completed: Introduction, Chapter 1, Chapter 2
Sections remaining: Chapter 3, Appendix A, Appendix B
Output file: C:\...\mission_module_draft.docx
```

---

## File Access Rules — CRITICAL

### Use MCP Filesystem Tools for Windows

The project is on a **Windows machine**. Use MCP filesystem tools:

| Tool | Use For |
|------|---------|
| `filesystem:read_text_file` | Read project files |
| `filesystem:write_file` | Create/overwrite files (SAFE for JSON) |
| `filesystem:edit_file` | Small targeted edits (AVOID for JSON with special chars) |
| `filesystem:list_directory` | Check folder contents |

### NEVER Use Bash for Windows Paths

```
❌ bash: cat C:\Users\...     # WILL FAIL
❌ bash: grep ... C:\Users\... # WILL FAIL
✅ filesystem:read_text_file   # CORRECT
```

### The edit_file Corruption Warning

`filesystem:edit_file` can corrupt files containing em-dashes (—), smart quotes, or other special characters. For files like `npc_roster.json`:

**ALWAYS use this pattern:**
1. `filesystem:read_text_file` — read the whole file
2. Parse/modify in your response (mentally or via logic)
3. `filesystem:write_file` — write the complete modified file

**NEVER use `filesystem:edit_file` on:**
- `npc_roster.json` (contains em-dashes throughout)
- Any JSON with user-generated content
- Files with non-ASCII characters

---

## Token Efficiency

### Don't Re-read What You Just Wrote

If you just wrote a file, you know its contents. Don't read it again to "verify" unless there's a specific concern.

### Summarize Large Data

When logging checkpoint data, summarize rather than copy:
```markdown
# Good
NPCs added: Serrik Dhal, Lady Cerys (+7 others, see roster)

# Bad (wastes tokens)
NPCs added: [full JSON of all 9 NPCs...]
```

### Use the Worklog as Memory

The worklog persists across sessions. Put anything you'd need to remember there, not in conversation history that will be lost.

---

## Example: NPC Roster Merge

### Step 1: Create Worklog
```markdown
# Worklog: Add 9 Faction Leaders to NPC Roster
**Started:** 2026-03-29 00:30 UTC
**Status:** IN PROGRESS

## Task Summary
Add 9 missing faction leader NPCs to npc_roster.json for mission builder integration.

## Steps
- [ ] 1. Read current npc_roster.json (verify count)
- [ ] 2. Prepare 9 new faction leader entries
- [ ] 3. Merge entries (check for duplicates)
- [ ] 4. Write updated roster
- [ ] 5. Verify new count

## Leaders to Add
1. Serrik Dhal (Iron Fang)
2. Lady Cerys Valemont (Argent Blades)
3. High Apostle Yzura (Serpent Choir)
4. The Widow (Obsidian Lotus)
5. Senior Archivist Pell (Glass Sigil)
6. Mari Fen (Adventurers Guild)
7. Eir Velan (Guild of Ashen Scrolls)
8. Director Myra Kess (FTA)
9. Brother Thane (The Returned)
```

### Step 2-5: Execute with Progress Updates

Update the worklog after each step. If interrupted, the next session can read the worklog and resume.

---

## Quick Reference

| Situation | Action |
|-----------|--------|
| Starting multi-step task | Create worklog first |
| Completing a step | Update worklog immediately |
| Session ends unexpectedly | Worklog preserves state |
| User says "continue" | Read worklog, resume from checkpoint |
| Large file edit | Read → modify → write_file (not edit_file) |
| Need to verify state | Check worklog, not re-read all files |

---

## Triggers

This skill activates when:
- Task has 3+ steps
- User mentions "continue", "resume", "retry", "pick up"
- Working with batch operations (multiple NPCs, files, etc.)
- Any operation that could be interrupted
- User explicitly asks for logging/checkpointing
