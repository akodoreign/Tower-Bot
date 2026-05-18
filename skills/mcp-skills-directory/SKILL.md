---
name: mcp-skills-directory
description: CRITICAL - Claude has WRITE ACCESS to the local skills directory. When creating skills, saving skill files, or the user asks to "install a skill", "save this skill", "add a skill", or "put this in skills", write directly to C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills. Do NOT save skills to /mnt/user-data/outputs - that's a workaround. You have DIRECT ACCESS via MCP filesystem tools. Use this skill whenever creating, modifying, or organizing skills.
---

# MCP Skills Directory Access

## YOU HAVE DIRECT WRITE ACCESS

**Skills Directory:** `C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills`

You can read AND write to this directory using MCP filesystem tools:
- `filesystem:write_file`
- `filesystem:create_directory`
- `filesystem:edit_file`
- `filesystem:move_file`

---

## When Creating a New Skill

**DO THIS:**
```
1. filesystem:create_directory → C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\{skill-name}
2. filesystem:write_file → C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\{skill-name}\SKILL.md
```

**DON'T DO THIS:**
- ❌ Save to `/mnt/user-data/outputs` and tell user to move it
- ❌ Say "I can't write to that location"
- ❌ Ask user to manually create the folder

---

## Skill File Structure

```
C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\
├── {skill-name}/
│   ├── SKILL.md          # Required - main skill file
│   ├── references/       # Optional - supporting docs
│   └── scripts/          # Optional - helper scripts
```

---

## Existing Skills in Directory

Check what's already there before creating duplicates:
```
filesystem:list_directory → C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills
```

---

## Triggers

Use this skill when user says:
- "create a skill"
- "save this skill"
- "install this skill"
- "add a skill for..."
- "put this in my skills"
- "write a skill"
- Any request to persist a skill

---

## Quick Reference

| Action | Command |
|--------|---------|
| List skills | `filesystem:list_directory` on skills path |
| Create skill folder | `filesystem:create_directory` |
| Write SKILL.md | `filesystem:write_file` |
| Edit existing skill | `filesystem:edit_file` or `filesystem:write_file` |
| Read skill | `filesystem:read_text_file` |

**Path:** `C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills`

You have full access. Use it.
