---
name: stepped-operations
description: Logged stepped operations with checkpoint/resume support. Use this skill for ANY multi-step task that could be interrupted (batch edits, large file operations, data migrations, multiple NPC updates, document generation). CRITICAL - when user says 'retry', 'continue', 'pick up where you left off', or 'got cut off', this means RESUME from the last completed step, NOT start over. Always create worklogs, track progress, and design operations to be idempotent and resumable.
---

# Stepped Operations Skill

## Core Principle

**Every operation that touches multiple items MUST be resumable.**

When the server cuts you off mid-operation, ALL progress is lost unless you've been logging. This skill ensures you can always pick up where you left off.

---

## The Three Laws

### 1. LOG BEFORE YOU ACT
```
✗ WRONG: Make 50 edits, get cut off at #23, lose everything
✓ RIGHT: Log each edit as you go, resume from #24 on retry
```

### 2. DESIGN FOR INTERRUPTION
```
✗ WRONG: Build giant data structure, write at end
✓ RIGHT: Process item → write immediately → next item
```

### 3. RETRY = RESUME
```
✗ WRONG: User says "retry" → Start completely over
✓ RIGHT: User says "retry" → Check worklog → Resume from last checkpoint
```

---

## Worklog Pattern

For any multi-item operation, create a worklog file FIRST:

```markdown
# Operation Worklog: [Task Name]
Created: [timestamp]

## Status: IN_PROGRESS | COMPLETED | FAILED

## Completed Items
- [x] Item 1 — completed at [time]
- [x] Item 2 — completed at [time]
- [ ] Item 3 — PENDING
- [ ] Item 4 — PENDING

## Last Checkpoint
Item: Item 2
Index: 2 of 50
Time: [timestamp]

## Resume Instructions
Start from Item 3
```

---

## Implementation Pattern

### For File Edits (like NPC roster updates)

```python
# PATTERN: Logged batch updates

import json
from pathlib import Path
from datetime import datetime

def batch_update_with_logging(items_to_update: dict, target_file: Path, worklog_file: Path):
    """Update items one at a time with checkpoint logging."""
    
    # Load existing worklog or create new
    if worklog_file.exists():
        worklog = json.loads(worklog_file.read_text())
        completed = set(worklog.get('completed', []))
        print(f"RESUMING: {len(completed)} items already done")
    else:
        worklog = {'completed': [], 'started': datetime.now().isoformat()}
        completed = set()
    
    # Load target data
    data = json.loads(target_file.read_text())
    
    # Process each item
    for name, new_value in items_to_update.items():
        if name in completed:
            print(f"SKIP (already done): {name}")
            continue
        
        # DO THE UPDATE
        for item in data:
            if item.get('name') == name:
                item['field'] = new_value
                break
        
        # IMMEDIATELY LOG SUCCESS
        worklog['completed'].append(name)
        worklog['last_checkpoint'] = name
        worklog['checkpoint_time'] = datetime.now().isoformat()
        worklog_file.write_text(json.dumps(worklog, indent=2))
        
        print(f"DONE: {name} ({len(worklog['completed'])}/{len(items_to_update)})")
    
    # Write final data
    target_file.write_text(json.dumps(data, indent=2))
    worklog['status'] = 'COMPLETED'
    worklog_file.write_text(json.dumps(worklog, indent=2))
```

### For Sequential Operations

```python
# PATTERN: Numbered steps with checkpoints

STEPS = [
    ("step_1", "Read source file", read_source),
    ("step_2", "Parse data", parse_data),
    ("step_3", "Transform items", transform_items),
    ("step_4", "Write output", write_output),
]

def run_with_checkpoints(worklog_path: Path):
    # Load checkpoint
    if worklog_path.exists():
        checkpoint = json.loads(worklog_path.read_text())
        start_from = checkpoint.get('next_step', 'step_1')
    else:
        start_from = 'step_1'
        checkpoint = {}
    
    # Find starting index
    start_idx = next(i for i, (step_id, _, _) in enumerate(STEPS) if step_id == start_from)
    
    # Run remaining steps
    for step_id, description, func in STEPS[start_idx:]:
        print(f"RUNNING: {step_id} — {description}")
        
        result = func(checkpoint.get('state', {}))
        
        # Checkpoint after each step
        checkpoint['completed_steps'] = checkpoint.get('completed_steps', []) + [step_id]
        checkpoint['next_step'] = STEPS[STEPS.index((step_id, description, func)) + 1][0] if ... else 'DONE'
        checkpoint['state'] = result
        checkpoint['last_update'] = datetime.now().isoformat()
        worklog_path.write_text(json.dumps(checkpoint, indent=2))
```

---

## Retry Detection

When user message contains ANY of these, CHECK THE WORKLOG FIRST:

| User Says | Action |
|-----------|--------|
| "retry" | Resume from last checkpoint |
| "continue" | Resume from last checkpoint |
| "try again" | Resume from last checkpoint |
| "got cut off" | Resume from last checkpoint |
| "pick up where" | Resume from last checkpoint |
| "keep going" | Resume from last checkpoint |
| "finish this" | Resume from last checkpoint |
| "what's left" | Report remaining items |

### Detection Code

```python
RETRY_SIGNALS = [
    'retry', 'continue', 'try again', 'cut off', 'pick up',
    'keep going', 'finish', 'remaining', 'left off', 'resume'
]

def is_retry_request(user_message: str) -> bool:
    msg_lower = user_message.lower()
    return any(signal in msg_lower for signal in RETRY_SIGNALS)
```

---

## Worklog File Locations

### For Tower Bot Project
```
C:\Users\akodoreign\Desktop\chatGPT-discord-bot\logs\
├── gazetteer_npc_worklog.md      # NPC location updates
├── mission_batch_worklog.json    # Mission document generation
├── code_refactor_worklog.md      # Cog refactoring progress
└── [operation]_worklog.[ext]     # Any batch operation
```

### Naming Convention
```
{operation_name}_worklog.{json|md}
```

---

## Pre-Operation Checklist

Before starting ANY batch operation:

- [ ] Create worklog file with all items listed
- [ ] Mark initial status as IN_PROGRESS
- [ ] Identify resumable chunks (items that can be done independently)
- [ ] Plan checkpoint frequency (every item? every 5 items?)
- [ ] Test resume logic on first 2 items before running full batch

---

## Example: NPC Location Update Worklog

```markdown
# NPC Location Updates Worklog
Created: 2026-03-27T11:44:00Z
Operation: Update 26 NPCs to canonical gazetteer locations

## Status: IN_PROGRESS

## Completed (15/26)
- [x] Gurthok Ironhide → Underbelly Warrens
- [x] Zephyrus Sylphim → Outer Wall, North Gate
- [x] Arin Obsidianwhisper → Outer Wall, The Fringe
... (more completed items)

## Pending (11/26)
- [ ] Lysandra Stardust
- [ ] Elysia Thornshadow
... (remaining items)

## Last Checkpoint
Name: Arin Obsidianwhisper
Index: 15 of 26
Time: 2026-03-27T12:30:00Z

## Resume Command
Run fix script starting from index 15 (Lysandra Stardust)
```

---

## Recovery Protocol

When resuming after interruption:

1. **Read worklog** — identify last successful checkpoint
2. **Report status** — "Found worklog: 15 of 26 items completed"
3. **Confirm with user** — "Resume from Lysandra Stardust?"
4. **Continue operation** — start from checkpoint, not beginning
5. **Update worklog** — mark newly completed items

---

## Anti-Patterns to AVOID

### ❌ Building in Memory, Writing at End
```python
# BAD - All progress lost on interrupt
results = []
for item in items:
    results.append(process(item))
write_all(results)  # Never reached if cut off
```

### ❌ Assuming Fresh Start
```python
# BAD - Ignores previous progress
def handle_retry(user_msg):
    if 'retry' in user_msg:
        start_from_beginning()  # WRONG
```

### ❌ No Progress Tracking
```python
# BAD - No way to know what's done
for item in items:
    update(item)
    # If cut off here, no record of which items completed
```

---

## Quick Reference

| Operation Type | Checkpoint Frequency | Worklog Format |
|----------------|---------------------|----------------|
| File edits | Every item | JSON |
| NPC updates | Every NPC | Markdown |
| Code generation | Every file | Markdown |
| Data migration | Every 10 rows | JSON |
| Document batch | Every document | JSON |

---

## When This Skill Triggers

- Any operation updating multiple items
- User mentions "batch", "all", "multiple", "several"
- Previous operation was interrupted
- User says "retry", "continue", "finish", "resume"
- Working with large data files (>50 items)
- Operations that take >30 seconds

**Remember: If it can be interrupted, it MUST be resumable.**
