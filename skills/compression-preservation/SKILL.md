---
name: compression-preservation
description: "Meta-skill for preserving context across conversation compactions. Use this skill BEFORE any context compression to ensure important session knowledge is captured in persistent skills. This prevents knowledge loss when conversations are compacted."
---

# Compression Preservation — Never Lose Session Knowledge

## The Problem

When a conversation context window fills up and gets compacted, valuable session-specific knowledge is summarized or lost:
- Decisions made and their rationale
- Bugs discovered and how they were fixed
- Patterns learned during debugging
- Project-specific conventions discovered
- Relationships between files/systems
- Edge cases encountered
- Things that didn't work (and why)

## The Solution

**Before compression happens, write skills that capture the knowledge.**

Skills persist across sessions. They don't get compacted. They're available in future conversations.

---

## What To Capture

### 1. **Bug Fixes & Root Causes**

When you fix a non-obvious bug, create or update a skill:

```markdown
## Bug: [Description]
**Symptom:** What the user saw
**Root Cause:** Why it happened
**Fix:** What was changed
**Files:** Which files were modified
**Prevention:** How to avoid this in the future
```

### 2. **Architecture Decisions**

When you discover or decide on a pattern:

```markdown
## Pattern: [Name]
**Context:** Why this pattern exists
**Implementation:** How it works
**Files:** Where it's implemented
**Gotchas:** What to watch out for
```

### 3. **File Relationships**

When you learn how files connect:

```markdown
## System: [Name]
**Entry Point:** Where it starts
**Flow:** How data/control moves
**Dependencies:** What it needs
**Outputs:** What it produces
```

### 4. **Things That Didn't Work**

Failed approaches are valuable knowledge:

```markdown
## Failed Approach: [What was tried]
**Why it seemed like a good idea:** Initial reasoning
**Why it failed:** What went wrong
**Alternative:** What worked instead
```

### 5. **Project Conventions**

Unwritten rules discovered through work:

```markdown
## Convention: [Name]
**Rule:** What to do
**Rationale:** Why it matters
**Examples:** Show correct usage
**Anti-patterns:** Show what not to do
```

---

## When To Write Skills

### Always Write/Update When:

- You fix a bug that took more than 5 minutes to diagnose
- You discover an undocumented relationship between systems
- You make a decision that future-you needs to remember
- You learn something about the project that isn't in the code
- You're about to be compacted and have session-specific knowledge

### Update Existing Skills When:

- The `tower-bot-files` file map changes (new files, deleted files, refactors)
- A convention you documented changes
- You learn more about a system you previously documented

### Create New Skills When:

- You've worked on a new system not covered by existing skills
- You've learned a category of knowledge that deserves its own skill
- The existing skill would become too long (>500 lines)

---

## Skill Naming Conventions

| Type | Naming Pattern | Example |
|------|----------------|---------|
| System documentation | `{system-name}` | `news-feed-system` |
| Bug/fix collection | `{area}-gotchas` | `discord-py-gotchas` |
| Conventions | `{project}-conventions` | `tower-bot-conventions` |
| Patterns | `{pattern-name}-pattern` | `cog-loading-pattern` |
| Workflows | `{workflow-name}-workflow` | `mission-generation-workflow` |

---

## Pre-Compression Checklist

Before a conversation is compacted, ask yourself:

- [ ] Did I fix any bugs? Document in a skill.
- [ ] Did I learn how systems connect? Update `tower-bot-files` or create a system skill.
- [ ] Did I discover any conventions? Document them.
- [ ] Did I make any decisions? Record the rationale.
- [ ] Did anything NOT work? Record the failed approaches.
- [ ] Did I create any new files? Update `tower-bot-files`.
- [ ] Is there session context that would be lost? Write a skill.

---

## Template: Quick Session Capture Skill

When compression is imminent and you need to capture everything fast:

```markdown
---
name: session-{date}-{topic}
description: "Session capture for {date} — {brief description of work done}"
---

# Session: {Topic}
Date: {YYYY-MM-DD}

## What Was Done
- {Task 1}
- {Task 2}

## Key Decisions
- {Decision 1}: {Rationale}
- {Decision 2}: {Rationale}

## Files Changed
- {file1}: {what changed}
- {file2}: {what changed}

## Bugs Fixed
### {Bug 1}
- Symptom: {what was seen}
- Cause: {why it happened}
- Fix: {what was changed}

## Patterns Learned
- {Pattern}: {Description}

## Open Questions / Future Work
- {Question or TODO}
```

---

## Example: What This Skill Would Capture From Today's Session

If this skill existed at the start of today's session, I would have created:

### `news-feed-formatting-fix` skill:
- Documented the timestamp/content concatenation bug
- Root cause: single `\n` collapsed by Discord
- Fix: changed to `\n\n` at all return points
- Files affected: `news_feed.py` lines with `_dual_timestamp()`

### Updated `tower-bot-files`:
- Added the new `skills/` directory
- Added all 4 creative writing skills

### `prose-quality-prompts` skill:
- Documented the PROSE QUALITY section added to `_build_prompt()`
- Listed anti-purple-prose rules
- Captured the "something must HAPPEN" principle

---

## Remember

**Skills are your external memory. Use them.**

When in doubt, write a skill. A skill that's never read costs nothing. Knowledge lost to compression costs time and frustration.
