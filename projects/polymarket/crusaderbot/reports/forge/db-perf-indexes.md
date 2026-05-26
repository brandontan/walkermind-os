# WARP•FORGE Report — db-perf-indexes

**Branch:** WARP/R00T-db-perf-indexes
**Validation Tier:** MINOR
**Claim Level:** FOUNDATION
**Validation Target:** DB index coverage on FK columns + unused index cleanup
**Not in Scope:** query plan changes, table partitioning, vacuuming, query rewrites

---

## 1. What was built

Migration 056 (`migrations/056_db_perf_indexes.sql`):

**Added 9 FK covering indexes** on hot and warm query paths:
- `orders(market_id)` — position open/close joins against orders
- `positions(market_id)` — all per-market position lookups
- `positions(order_id)` — fill/position join path
- `users(referrer_id)` — referral attribution queries
- `idempotency_keys(user_id)` — dedup checks per user
- `user_signal_subscriptions(feed_id)` — signal evaluator subscription lookup
- `fees(order_id)` — fee reconciliation against orders
- `fees(referrer_id)` — referral fee attribution
- `copy_trade_events(position_id)` — copy event → position join

**Dropped 1 duplicate index:**
- `idx_fees_trade_id` — exact duplicate of `idx_fees_trade` (Supabase advisor WARN)

**Dropped 10 confirmed-unused cold-table indexes** (zero scans reported by Supabase advisor):
- `idx_copy_trade_events_user_id`, `idx_copy_trade_events_market`, `idx_copy_trade_events_created_at`
- `idx_referral_events_referrer`
- `idx_audit_log_event`, `idx_audit_log_created`
- `idx_mode_change_events_user`, `idx_mode_change_events_reason`
- `idx_redeem_queue_failed`
- `idx_fees_user`

Preserved indexes on hot read paths (`idx_positions_is_demo`, `idx_orders_is_demo`, `idx_ledger_is_demo`, `idx_signal_publications_is_demo`, `idx_positions_force_close_intent`, `idx_positions_close_failure`, `idx_fills_ts`, `idx_portfolio_snapshots_user_at`, `idx_signal_publications_is_demo`).

---

## 2. Current system architecture

DB layer: Supabase PostgreSQL (project `ykyagjdeqcgcktnpdhes`), asyncpg pool (max 10), 43 public tables with RLS enabled. Migration runner is idempotent (IF NOT EXISTS / IF EXISTS guards).

---

## 3. Files created / modified

- `projects/polymarket/crusaderbot/migrations/056_db_perf_indexes.sql` — NEW
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — updated [IN PROGRESS]
- `projects/polymarket/crusaderbot/reports/forge/db-perf-indexes.md` — NEW (this file)

---

## 4. What is working

- Migration is fully idempotent (`IF NOT EXISTS` / `IF EXISTS` on every statement)
- No data changes — index-only DDL
- All FK columns being indexed are already confirmed live in production schema
- Preserves all hot-path partial indexes (`is_demo`, `force_close_intent`, `close_failure`, `fills_ts`)

---

## 5. Known issues

- DB connection slots were exhausted during this session (Supabase direct `FATAL 53300`). The app pool (10 connections) is fine. Root cause: MCP tool saturating direct Postgres slots during multi-query session. Consider switching `DATABASE_URL` to the Supabase Supavisor pooler URL (6543 port) — database.py already supports it (`statement_cache_size=0`). Requires WARP🔹CMD to obtain pooler DSN from Supabase dashboard and set as Fly secret.

---

## 6. What is next

- Apply migration 056 to production (auto-applies on next Fly.io deploy)
- WARP🔹CMD decision: switch DATABASE_URL to Supabase Supavisor pooler to avoid direct connection saturation
- copy_targets legacy cleanup (follow-up lane): disable `/copytrade add/remove/list` slash command + DROP TABLE copy_targets

**Suggested Next Step:** Deploy this migration (ride next Fly.io deploy). Then evaluate Supavisor pooler switch.
