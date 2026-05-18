# Npcs

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Npcs subsystem handles **2 routes** and touches: auth, db, cache, payment.

## Routes

- `GET` `/api/npcs` [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`
- `GET` `/api/npcs/<path:npc_name>` params(npc_name) [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`

## Related Models

- **npcs** (8 fields) → [database.md](./database.md)

## Source Files

Read these before implementing or modifying this subsystem:
- `archive\backups_old\backups\codex_20260507_172046\app.py`

---
_Back to [overview.md](./overview.md)_