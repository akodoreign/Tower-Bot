# Area-maps

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Area-maps subsystem handles **2 routes** and touches: auth, db, cache, payment.

## Routes

- `GET` `/api/area-maps` [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`
- `GET` `/area-maps/<path:filename>` params(filename) [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `archive\backups_old\backups\codex_20260507_172046\app.py`

---
_Back to [overview.md](./overview.md)_