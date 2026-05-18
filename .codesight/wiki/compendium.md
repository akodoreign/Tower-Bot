# Compendium

> **Navigation aid.** Route list and file locations extracted via AST. Read the source files listed below before implementing or modifying this subsystem.

The Compendium subsystem handles **3 routes** and touches: auth, db, cache, queue, payment.

## Routes

- `GET` `/api/compendium/search` [auth, db, cache, queue, payment]
  `Webpage\app.py`
- `GET` `/api/compendium/documents` [auth, db, cache, queue, payment]
  `Webpage\app.py`
- `GET` `/api/compendium/document/<doc_id>` params(doc_id) [auth, db, cache, queue, payment]
  `Webpage\app.py`

## Source Files

Read these before implementing or modifying this subsystem:
- `Webpage\app.py`

---
_Back to [overview.md](./overview.md)_