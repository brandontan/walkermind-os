# WARP•FORGE REPORT — hotfix-db-pooler-fix

**Validation Tier:** STANDARD
**Claim Level:** FOUNDATION
**Validation Target:** database.py startup connection-type logging
**Not in Scope:** migration runner logic, statement_cache_size parameter, any other file
**Suggested Next Step:** WARP🔹CMD review; merge when satisfied

---

## 1. What was built

Replaced the port-gated Supavisor warning in `database.py` with a
connection-type logger (`_log_connection_type`) that:

- Emits `WARNING` whenever `DATABASE_URL` host contains `pooler.supabase.com`
  (regardless of port).
- Emits `INFO` when the URL is a direct connection (no pooler host hint).

Old behavior: warning fired only when host matched `pooler.supabase` AND
port was exactly 6543. After the Fly.io secret was updated to a direct
connection URL, the old warning was silent and there was no confirmation
log that a direct connection was actually in use. The new logic provides
explicit startup confirmation in both cases.

`statement_cache_size=0` in `create_pool()` is unchanged — it remains
unconditional as required.

---

## 2. Current system architecture

No architectural change. `database.py` is the asyncpg pool factory. The
connection-type log fires once per process at pool initialisation time,
before the pool is created. All other database.py surfaces (ping, kill
switch, migrations, health) are untouched.

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/database.py`
  - Replaced `_SUPAVISOR_HOST_HINT` + `_SUPAVISOR_TRANSACTION_PORT` constants
    with `_POOLER_HOST_HINT = "pooler.supabase.com"`
  - Replaced `_warn_if_supavisor_transaction_pool()` with `_log_connection_type()`
  - Updated call site in `init_pool()` (line 63)

- `projects/polymarket/crusaderbot/tests/test_database.py`
  - Updated 2 existing test assertions to match new message text
  - Renamed `test_init_pool_does_not_warn_for_session_pool_port` →
    `test_init_pool_warns_for_pooler_host_any_port` (behaviour change:
    port 5432 on a pooler host now correctly triggers the warning)
  - Updated `test_init_pool_does_not_warn_for_non_supabase_host` assertion
    string from `"Supavisor transaction pool"` to `"connection pooler"`
  - Added `test_init_pool_logs_info_for_direct_connection`

---

## 4. What is working

- 11/11 `test_database.py` tests pass.
- Direct connection URL → `INFO  DATABASE_URL uses direct connection (host=...)`.
- Pooler URL (any port) → `WARNING  DATABASE_URL points at Supabase connection pooler (host=...)`.
- Non-supabase host → no pooler warning; INFO for direct connection.
- Malformed DSN → silent noop (existing behaviour preserved).
- `statement_cache_size=0` unconditional (no change).

---

## 5. Known issues

None.

---

## 6. What is next

WARP🔹CMD review and merge.
