# WARP•FORGE — rls-enable-anon-lockout

Validation Tier: MAJOR
Claim Level: FOUNDATION
Validation Target: migrations/046_enable_rls_anon_lockout.sql correctness + safety reasoning (does NOT include applying the migration to production).
Not in Scope: applying the migration (review-only per WARP🔹CMD); designing per-row anon/authenticated policies (no anon consumer exists today); F-HIGH-2 strategy wiring (separate lane WARP/autotrade-strategy-wiring).
Suggested Next Step: WARP🔹CMD review → merge → next Fly deploy auto-applies it via database.py; re-run Supabase advisor to confirm 0 RLS-disabled tables.

## 1. What was built

A single forward migration, `migrations/046_enable_rls_anon_lockout.sql`, that enables Row Level Security on every one of the 42 tables in the `public` schema.

Origin: the Supabase security advisor reported `rls_disabled` at CRITICAL priority — all 42 public tables (including `users`, `wallets`, `positions`, `orders`, `ledger`) had RLS disabled, leaving them fully readable/writable by the Supabase `anon` and `authenticated` roles (i.e. anyone holding the project anon key).

The migration uses a `DO` block that iterates a fixed array of the 42 table names, checks each exists in `pg_tables`, and runs `ALTER TABLE public.<t> ENABLE ROW LEVEL SECURITY`. It is:
- Idempotent — enabling RLS on an already-enabled table is a no-op.
- Non-destructive — `ENABLE` (not `FORCE`), and no `DROP`/data change.
- Reversible — `ALTER TABLE public.<t> DISABLE ROW LEVEL SECURITY`.

No policies are created. With RLS enabled and no policy, `anon`/`authenticated` are denied by default — the intended lockout.

## 2. Current system architecture

Data access boundary (verified):
- Backend (bot + webtrader API) connects to Postgres via `DATABASE_URL` as role `postgres`. `postgres` owns all 42 tables and has `rolbypassrls = TRUE`, so a non-FORCE RLS policy is bypassed — backend access is unchanged.
- `service_role` also has `rolbypassrls = TRUE` (Supabase default).
- Frontend (`webtrader/frontend`) calls only the backend (`/api/web/*` REST + `/api/web/stream` SSE). It does not instantiate a Supabase client and never uses the anon key (no `createClient`, no direct `.from()` reads, no Supabase Realtime channel).

Net effect of the migration: `anon`/`authenticated` (rolbypassrls = FALSE, no policy) lose all table access; the backend (table owner) is unaffected. No legitimate consumer is impacted.

Migration runner: `database.py:126` globs `migrations/*.sql` sorted and executes them on startup, so `046_*` runs automatically on the next deploy.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/migrations/046_enable_rls_anon_lockout.sql
- projects/polymarket/crusaderbot/reports/forge/rls-enable-anon-lockout.md

Modified:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md (Status, KNOWN ISSUES, NEXT PRIORITY)
- projects/polymarket/crusaderbot/state/WORKTODO.md (Production Integrity item)
- projects/polymarket/crusaderbot/state/CHANGELOG.md (lane entry)

## 4. What is working

Verified against the live CrusaderBot project (read-only) before authoring:
- All 42 table names in the migration array exist in `public` (matched_existing = 42, named = 42, typos_missing = none).
- The array covers exactly every public table (total_public_tables = 42, public_tables_not_in_list = none) — no table is left exposed.
- None of the 42 tables currently has RLS enabled (already_rls_enabled = none) — the migration is both meaningful and complete.
- Ownership/role facts confirming backend safety: all 42 tables owned by `postgres`; `postgres` and `service_role` have `rolbypassrls = TRUE`; `anon`/`authenticated` do not.

## 5. Known issues

- The migration has NOT been applied (review-only by WARP🔹CMD direction). It will auto-apply on the next Fly deploy via `database.py`. If a future feature ever adds a direct browser→Supabase data path using the anon key, it will be denied until scoped RLS policies are written — that is the intended secure default, not a regression.
- Pre-apply assumption to confirm at deploy: production `DATABASE_URL` connects as `postgres` (or another BYPASSRLS/owner role). Verified true today; flagged so it is re-checked if the connection role ever changes.
- Unrelated advisories remain open (deferred): `function_search_path_mutable` WARN ×9; WebTrader 690 kB single-chunk bundle. Not in this lane's scope.

## 6. What is next

- WARP🔹CMD review of this MAJOR-tier security migration.
- On merge + deploy: re-run the Supabase advisor (`security`) and confirm the `rls_disabled` finding clears to 0 tables.
- Optional follow-up lane: pin `search_path` on the 9 flagged trigger/notify functions.
