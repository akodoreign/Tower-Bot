# Modules

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Modules subsystem handles **4 routes** and touches: auth, db, cache, payment.

## Routes

- `GET` `/api/modules` [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`
- `GET` `/modules/<slug>/` params(slug) [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`
- `GET` `/modules/<slug>` params(slug) [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`
- `GET` `/modules/<slug>/<path:filename>` params(filename, slug) [auth, db, cache, payment]
  `archive\backups_old\backups\codex_20260507_172046\app.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `archive\backups_old\backups\codex_20260507_172046\app.py`

---
_Back to [overview.md](./overview.md)_