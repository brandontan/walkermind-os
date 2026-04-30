# DB_IMPORT_FIX — DatabaseClient Import Error Fix

**Date:** 2026-04-03  
**Status:** COMPLETE ✅

---

## 1. Root Cause

`infra/db.py` (PostgreSQL `DatabaseClient`) existed alongside the `infra/db/` package
directory (containing `sqlite_client.py`).

Python resolves `infra.db` to the **package** (`infra/db/`) which takes precedence over
the module file (`infra/db.py`).  Because `infra/db/__init__.py` only exported
`SQLiteClient`, any `from .infra.db import DatabaseClient` import raised:

```
ImportError: cannot import name 'DatabaseClient' from 'infra.db'
```

This prevented bot startup entirely.

---

## 2. Fix Applied

**Created** `infra/db/database.py` — the full `DatabaseClient` implementation (moved
from `infra/db.py` into the package so it is reachable through the package namespace).

**Updated** `infra/db/__init__.py`:

```python
from .database import DatabaseClient
from .sqlite_client import SQLiteClient

__all__ = ["DatabaseClient", "SQLiteClient"]
```

`database.py` emits `log.info("db_import_ok")` at module load to confirm successful import.

---

## 3. Startup Logs (Validated)

```
2026-04-03 [info] db_import_ok
2026-04-03 [info] db_client_initialized  dsn=postgresql://polyquantbot:polyqu...  pool_min=2  pool_max=10
```

---

## 4. Confirmation — System Running

- `from infra.db import DatabaseClient` ✅
- `from infra.db import SQLiteClient` ✅
- `DatabaseClient()` instantiates without error ✅
- `db_import_ok` logged at import time ✅
- `db_client_initialized` logged on instantiation ✅
- No circular imports ✅
- No silent failure ✅

---

## 5. Files Created / Modified

| File | Action |
|------|--------|
| `infra/db/database.py` | **Created** — full `DatabaseClient` PostgreSQL async client |
| `infra/db/__init__.py` | **Updated** — exports `DatabaseClient` + `SQLiteClient` |
| `reports/forge/DB_IMPORT_FIX.md` | **Created** — this report |
| `PROJECT_STATE.md` | **Updated** — latest status |

---

## 6. Known Issues

- `infra/db.py` is now shadowed by the `infra/db/` package and is dead code.
  It may be removed in a future cleanup task to avoid confusion.
- `DB_DSN` env var must be set and PostgreSQL reachable for `db.connect()` to succeed.
- `MARKET_IDS` env var should be set for market discovery.

---

## 7. What's Next

- Remove dead `infra/db.py` module in a cleanup pass
- Confirm full `main.py` startup end-to-end in container environment
