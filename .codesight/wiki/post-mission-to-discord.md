# Post-mission-to-discord

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Post-mission-to-discord subsystem handles **1 routes** and touches: auth, db, cache, queue, payment.

## Routes

- `POST` `/api/post-mission-to-discord` [auth, db, cache, queue, payment]
  `Webpage\app.py`

## Related Models

- **mission_types** (9 fields) → [database.md](./database.md)

## Source Files

Read these before implementing or modifying this subsystem:
- `Webpage\app.py`

---
_Back to [overview.md](./overview.md)_