---
name: mcp-skills-access
description: MCP Skills Directory Access. Use this skill when creating, editing, or managing skills for James's environment. You have FULL WRITE ACCESS to the local skills directory. When creating new skills, write them DIRECTLY to the project skills folder - do NOT save to /mnt/user-data/outputs. Triggers on any mention of 'create a skill', 'new skill', 'write a skill', 'add skill', 'install skill', or skill management tasks.
---

# MCP Skills Directory Access

## CRITICAL: You Have Write Access

You can write skills **directly** to the project directory. Do NOT use `/mnt/user-data/outputs` for skills.

## Skills Directory Location

```
C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\
```

This directory is **WRITABLE** via the MCP filesystem tools.

---

## To Create a New Skill

1. Create the skill directory:
```
filesystem:create_directory
path: C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\{skill-name}\
```

2. Write the SKILL.md file:
```
filesystem:write_file
path: C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\{skill-name}\SKILL.md
content: (skill content)
```

3. Add any supporting files (references, scripts, assets) to the same directory

---

## Existing Skills in This Directory

| Skill | Purpose |
|-------|---------|
| `tower-bot` | Tower of Last Chance Discord bot patterns |
| `discord-bot-patterns` | discord.py patterns and cog architecture |
| `dnd5e-srd` | D&D 5e SRD RAG access |
| `dnd-mission-docx` | Mission document generation |
| `docx` | Word document creation |
| `pdf` | PDF manipulation |
| `skill-creator` | Creating and testing new skills |
| `Python311` | Python 3.11 compatibility |
| `web-artifacts-builder` | Web artifact patterns |

---

## DO NOT

- ❌ Save skills to `/mnt/user-data/outputs` 
- ❌ Tell user to "download and install" skills
- ❌ Assume skills directory is read-only

## DO

- ✅ Write directly to `C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\`
- ✅ Create subdirectory with skill name
- ✅ Include SKILL.md with proper frontmatter
- ✅ Add supporting files as needed

---

## Verification

After creating a skill, verify with:
```
filesystem:list_directory
path: C:\Users\akodoreign\Desktop\chatGPT-discord-bot\skills\{skill-name}
```

---

## Skill Availability

Skills in this directory are loaded by the MCP server and appear in `<available_skills>` automatically. No restart required for new skills to be recognized on the next conversation.
