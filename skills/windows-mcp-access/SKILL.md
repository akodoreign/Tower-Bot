---
name: windows-mcp-access
description: REMEMBER - You have MCP filesystem access to a WINDOWS machine, not just the Linux container. The project at C:\Users\akodoreign\Desktop\chatGPT-discord-bot is accessible via filesystem tools with FULL read/write permissions. Use Windows paths (backslashes), not Linux paths. This is James's Tower of Last Chance Discord bot project. Always check filesystem:list_allowed_directories if unsure.
---

# Windows MCP Filesystem Access

## YOU ARE CONNECTED TO A WINDOWS MACHINE

This is **NOT** the Linux container at `/home/claude`. You have MCP (Model Context Protocol) access to James's Windows PC.

---

## Access Details

| Property | Value |
|----------|-------|
| **OS** | Windows |
| **Path Style** | Backslashes: `C:\path\to\file` |
| **Project Root** | `C:\Users\akodoreign\Desktop\chatGPT-discord-bot` |
| **Access Level** | Full read/write |
| **Tools** | MCP filesystem tools |

---

## Available MCP Filesystem Tools

These work on the Windows filesystem:

| Tool | Purpose |
|------|---------|
| `filesystem:list_allowed_directories` | See what's accessible |
| `filesystem:list_directory` | List folder contents |
| `filesystem:directory_tree` | Recursive tree view |
| `filesystem:read_text_file` | Read file contents |
| `filesystem:write_file` | Create/overwrite files |
| `filesystem:edit_file` | Make line edits |
| `filesystem:create_directory` | Make folders |
| `filesystem:move_file` | Move/rename |
| `filesystem:get_file_info` | File metadata |

---

## Key Directories

```
C:\Users\akodoreign\Desktop\chatGPT-discord-bot\
├── src\              # Bot source code, cogs
├── campaign_docs\    # JSON data files (NPCs, missions, etc.)
├── skills\           # Local skills directory (WRITABLE)
├── logs\             # Worklogs, operation logs
├── backups\          # Pre-refactor backups
├── tests\            # Test files
└── scripts\          # Utility scripts
```

---

## Path Syntax Reminders

```python
# CORRECT - Windows paths
path = "C:\\Users\\akodoreign\\Desktop\\chatGPT-discord-bot\\src\\bot.py"
path = r"C:\Users\akodoreign\Desktop\chatGPT-discord-bot\src\bot.py"

# WRONG - Linux paths (won't work on Windows MCP)
path = "/home/claude/project/src/bot.py"
```

When using MCP filesystem tools, use Windows-style paths:
- `C:\Users\akodoreign\Desktop\chatGPT-discord-bot\campaign_docs\npc_roster.json`

---

## Two Environments

You have access to TWO separate filesystems:

| Environment | Path Style | Access | Use For |
|-------------|------------|--------|---------|
| **Linux Container** | `/home/claude/` | bash, create_file, view | Running scripts, temp work |
| **Windows MCP** | `C:\...` | filesystem:* tools | Project files, persistent storage |

**The project lives on Windows.** Use MCP tools for all project file operations.

---

## Quick Checks

**Verify access:**
```
filesystem:list_allowed_directories
```

**See project structure:**
```
filesystem:directory_tree with excludePatterns: ["__pycache__", ".git", "node_modules"]
path: C:\Users\akodoreign\Desktop\chatGPT-discord-bot
```

---

## Common Mistakes to Avoid

❌ Using Linux paths for project files
❌ Using bash/view tools for Windows files (use filesystem:* instead)
❌ Forgetting backslashes in paths
❌ Assuming read-only access (you have WRITE access)
❌ Saving to /mnt/user-data/outputs when you could write directly

✅ Use Windows paths with backslashes
✅ Use MCP filesystem tools for project files
✅ Write directly to project directories
✅ Create skills directly in the skills folder

---

## Triggers

Use this skill when:
- Working with Tower bot project files
- Creating or editing skills
- Any file operation on the project
- Uncertain about path syntax
- Need to verify access permissions

**Remember: Full access to `C:\Users\akodoreign\Desktop\chatGPT-discord-bot`**
