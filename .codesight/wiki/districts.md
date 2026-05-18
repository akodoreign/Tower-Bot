# Districts

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Districts subsystem handles **3 routes** and touches: auth, db, cache, payment.

## Routes

- `GET` `/api/districts` [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`
- `GET` `/api/districts/<district_name>/places` params(district_name) [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`
- `GET` `/api/districts/<district_name>/profile` params(district_name) [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `archive\backups_old\backups\codex_20260507_172046\app.py`

---
_Back to [overview.md](./overview.md)_