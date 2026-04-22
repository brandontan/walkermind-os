## 1. What was built

- Introduced a canonical DB runtime config contract via `DATABASE_URL` with explicit `DB_DSN` compatibility fallback, plus normalized SSL behavior (`sslmode=require`) for non-local database hosts.
- Hardened active DB clients (`infra/db.py` and `infra/db/database.py`) to consume the same canonical runtime DSN resolver so active runtime DB paths no longer diverge in env source semantics.
- Wired truthful DB dependency startup/readiness handling in `server/main.py` and `server/api/routes.py`:
  - startup now records explicit DB config/connection status without crashing the API process on DB unavailability,
  - `/ready` now includes `database_runtime` readiness dimensions and returns `503` when DB dependency is not truly connected.
- Updated root runtime messaging (`main.py`) from `DB_DSN` wording to canonical `DATABASE_URL` wording for startup failures.
- Added targeted tests for canonical DB config contract and DB readiness behavior.

## 2. Current system architecture (relevant slice)

- `infra/db/runtime_config.py` is now the canonical DB DSN parser/normalizer used by active runtime DB paths.
- `DatabaseClient` constructors in both active DB modules now resolve DSN from one shared source contract (`DATABASE_URL`, fallback `DB_DSN_COMPAT`).
- `server/main.py` startup path now performs bounded DB bootstrap (`connect_with_retry` + healthcheck) and stores DB truth in `RuntimeState`.
- `server/api/routes.py` `/ready` path now evaluates readiness across API boot, telegram state, and DB state (DB gate contributes to final `ready` vs `not_ready`).

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/polyquantbot/infra/db/runtime_config.py` (created)
- `projects/polymarket/polyquantbot/config/startup_validation.py`
- `projects/polymarket/polyquantbot/infra/db.py`
- `projects/polymarket/polyquantbot/infra/db/database.py`
- `projects/polymarket/polyquantbot/server/core/runtime.py`
- `projects/polymarket/polyquantbot/server/main.py`
- `projects/polymarket/polyquantbot/server/api/routes.py`
- `projects/polymarket/polyquantbot/main.py`
- `projects/polymarket/polyquantbot/tests/test_crusader_runtime_surface.py`
- `projects/polymarket/polyquantbot/tests/test_priority2_db_runtime_config_20260422.py` (created)
- `projects/polymarket/polyquantbot/reports/forge/phase10-5_01_priority2-db-readiness-hardening.md`
- `PROJECT_STATE.md`

## 4. What is working

- Canonical DSN source contract now resolves consistently for active runtime DB client usage paths.
- Non-local DSNs now enforce SSL contract behavior (`sslmode=require`) at parse/load time.
- `/ready` now reports DB dependency truth and blocks false-green readiness when DB config is missing or DB healthcheck does not pass.
- Startup no longer hard-crashes the control-plane API when DB is missing/unavailable; it remains up while exposing explicit DB-not-ready status.
- Missing DB/env state is surfaced explicitly via structured startup/readiness fields (`db_config_present`, `db_connected`, `db_last_error`).

## 5. Known issues

- Runtime acceptance evidence for real deploy DB connectivity (Fly/Supabase path) is not included in this FORGE pass and must be validated by SENTINEL/runtime environment checks.
- `DB_DSN` compatibility fallback remains intentionally present for transition continuity; removal can be scheduled after deploy env parity confirms `DATABASE_URL` usage everywhere.

## 6. What is next

- Execute SENTINEL MAJOR validation against this branch for startup/readiness behavior proof under unavailable DB and configured DB paths.
- After SENTINEL verdict, proceed with COMMANDER merge decision.

Validation Tier   : MAJOR
Claim Level       : NARROW INTEGRATION
Validation Target : Canonical DB config contract + startup/readiness truth for active runtime paths
Not in Scope      : User/session/link state migration to DB, broad persistence refactor, wallet lifecycle expansion, live-trading capability changes
Suggested Next    : SENTINEL validation required
