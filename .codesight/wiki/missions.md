# Missions

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Missions subsystem handles **2 routes** and touches: auth, db, cache, payment.

## Routes

- `GET` `/api/missions` [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`
- `GET` `/api/missions/<int:mission_id>` params(mission_id) [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`

## Related Models

- **missions** (11 fields) → [database.md](./database.md)
- **personal_missions** (6 fields) → [database.md](./database.md)

## Source Files

Read these before implementing or modifying this subsystem:
- `archive\backups_old\backups\codex_20260507_172046\app.py`

---
_Back to [overview.md](./overview.md)_