# WARP•FORGE Report — Lane 1C Demo Data Seeding

Branch: WARP/CRUSADERBOT-DEMO-SEED-DATA
Date: 2026-05-08 09:35 Asia/Jakarta
Issue: CRU-5
Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: migration 014 + seed/cleanup scripts + runbook (additive only — no runtime path touched)
Not in Scope: activation guards, execution router, risk gate, kill switch, scheduler, Telegram handler code, prod data, market sync job
Suggested Next Step: WARP•SENTINEL audit before merge.

---

## 1. What Was Built

A self-contained demo dataset behind an additive `is_demo BOOLEAN`
flag, plus operator-run seed and cleanup scripts gated by explicit env
guards. The dataset gives `/signals catalog`, `/dashboard`, and
`/pnl`-style surfaces realistic content for an investor / operator demo
without inventing runtime side-effects:

* 12 synthetic Polymarket-shaped markets (`demo-market-001…012`).
* 2 operator-curated signal feeds: "Polymarket Politics Watcher"
  (conservative, slug `demo-politics-watcher`) + "Polymarket Sports
  Edge" (moderate, slug `demo-sports-edge`).
* 10 entry signal publications spread across the last 12 hours with
  confidence scores 0.55–0.85 in `payload.confidence`.
* 2 demo users (`telegram_user_id = -1, -2`) at access tier 3
  (FUNDED), `auto_trade_on=FALSE` so the execution loop never picks
  them up.
* Demo wallets at paper balance $10,000 each (deposit address
  `0xDEMO…`, `hd_index` 999_999_001/002 — far above the live counter).
* Subscriptions: user1 → Politics Watcher; user2 → both feeds.
* 7-day paper-trade history (32 closed trades, ~58% win rate, sizes
  $80–$240, weighted toward recent days with 10 trades today) backed by
  matching `ledger.trade_close` rows so `wallet.ledger.daily_pnl()`
  returns a non-trivial number for today.

Idempotent on every layer: re-runs insert only missing rows. UUIDs
derive from a fixed namespace (`uuid5`), and `idempotency_key` /
`slug` / PK conflicts route through `ON CONFLICT DO NOTHING`.

The cleanup script deletes only `is_demo=TRUE` rows, runs in a single
transaction, and verifies a zero residual count post-commit. Both
scripts refuse to run unless their explicit env flag is set.

---

## 2. Current System Architecture (Lane 1C slice)

```
                   ┌─────────────────────────────────────────────┐
                   │ migrations/014_add_is_demo_flag.sql         │
                   │   adds is_demo BOOLEAN NOT NULL DEFAULT FALSE│
                   │   to: users, wallets, user_settings,         │
                   │        signal_feeds, signal_publications,    │
                   │        user_signal_subscriptions, markets,   │
                   │        orders, positions, ledger             │
                   │   + 4 partial indexes (high-cardinality only)│
                   │   + in-file ROLLBACK block (DROP COLUMN IF   │
                   │     EXISTS / DROP INDEX IF EXISTS)           │
                   └────────────────────┬────────────────────────┘
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        │                               │                               │
        ▼                               ▼                               ▼
┌───────────────┐             ┌─────────────────┐            ┌────────────────┐
│ seed_demo_    │             │ runtime         │            │ cleanup_demo_  │
│ data.py       │             │ (UNCHANGED)     │            │ data.py        │
│               │             │                 │            │                │
│ DEMO_SEED_    │             │ /signals reads  │            │ DEMO_CLEANUP_  │
│ ALLOW=1       │   writes    │ signal_feeds    │  reads     │ CONFIRM=1      │
│ required      │ ─────────►  │ (status='active')│ ◄────────  │ required       │
│               │             │                 │            │                │
│ idempotent    │             │ /dashboard /pnl │            │ deletes only   │
│ via uuid5 +   │             │ read wallets +  │            │ is_demo=TRUE   │
│ ON CONFLICT   │             │ ledger          │            │ rows + post-   │
│ DO NOTHING    │             │                 │            │ commit verify  │
└───────┬───────┘             └─────────────────┘            └────────┬───────┘
        │                                                             │
        │            both scripts share the same per-table             │
        │            allowlist; cleanup verifies zero residual         │
        └──────────────────────────────────────────────────────────────┘

Boundary guarantees:
* Migration is additive only. Existing rows get is_demo=FALSE.
* Activation guards NEVER touched (ENABLE_LIVE_TRADING /
  EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED).
* Seed never inserts into audit.log, system_settings, kill_switch, or
  kill_switch_history.
* Cleanup deletes are scoped via is_demo=TRUE on every WHERE clause;
  auxiliary user-FK tables (sessions / deposits / fees / etc.) are
  scoped via users.is_demo=TRUE selector ➜ ANY($1::uuid[]).
```

Idempotency contract:

* Markets keyed on stable text PK (`demo-market-NNN`).
* Users keyed on `telegram_user_id` UNIQUE (-1, -2).
* Wallets / user_settings keyed on `user_id` PK.
* Signal feeds keyed on `slug` UNIQUE.
* Publications keyed on deterministic `uuid5(NS, "pub:slug:market:side")`.
* Subscriptions guarded by partial UNIQUE
  `(user_id, feed_id) WHERE unsubscribed_at IS NULL`.
* Orders keyed on `idempotency_key = "demo-order-{user_id}-{idx}"`
  UNIQUE.
* Positions / ledger keyed on deterministic `uuid5` PKs.

---

## 3. Files Created / Modified

Created:
* projects/polymarket/crusaderbot/migrations/014_add_is_demo_flag.sql
* projects/polymarket/crusaderbot/scripts/__init__.py
* projects/polymarket/crusaderbot/scripts/seed_demo_data.py
* projects/polymarket/crusaderbot/scripts/cleanup_demo_data.py
* projects/polymarket/crusaderbot/docs/runbook/demo-data.md
* projects/polymarket/crusaderbot/reports/forge/demo-seed-data.md (this file)

Modified:
* projects/polymarket/crusaderbot/state/PROJECT_STATE.md (7 sections
  only, surgical)
* projects/polymarket/crusaderbot/state/WORKTODO.md (Right Now + R12
  Lane 1C row)
* projects/polymarket/crusaderbot/state/CHANGELOG.md (one append-only
  entry)

No runtime Python touched. No Telegram handler, scheduler, risk gate,
execution router, or activation-guard file modified.

---

## 4. What Is Working

Verified locally against a fresh Postgres 16 database (all 14
migrations applied):

* Forward migration 014 applied clean — 10 tables now carry `is_demo`,
  4 partial indexes created.
* Idempotent re-run: NOTICE on existing indexes, zero column changes.
* Rollback block executed cleanly — 0 leftover `is_demo` columns.
* Re-apply forward after rollback: clean.
* Seed (boss user telegram_user_id=1234567 pre-inserted as a stand-in
  for OPERATOR_CHAT_ID): 12 markets / 2 feeds / 2 users / 10 pubs /
  34 orders / 34 positions / 34 ledger rows inserted on first run.
* `/signals catalog` query: both demo feeds appear with `status=active`
  and accurate `subscriber_count` (Politics=2, Sports=1).
* `/pnl` ledger today's slice: -$10.36 (user 1), -$54.16 (user 2) —
  non-trivial paper P&L from the 58%-win-rate distribution.
* Re-run seed twice: no duplicate inserts; per-run insert-counters
  correctly drop to 0 on second run.
* Cleanup with non-demo records present (1 real user, 1 real market, 1
  real feed): all 135 demo rows deleted, all 4 non-demo rows preserved,
  post-commit verify returns 0 residual.
* Re-seed after cleanup: clean.
* Env guards: missing `DEMO_SEED_ALLOW=1` → exit 2 with refusal log;
  missing `DEMO_CLEANUP_CONFIRM=1` → exit 2 with refusal log; neither
  script opens a DB connection before the guard check.

Test suite: `pytest projects/polymarket/crusaderbot/tests/` →
**514 passed**. Above the 464 floor mandated by the AUTHORITY GATES
(no test count regression).

---

## 5. Known Issues

* The seed script reports `users=2 feeds=2` even on subsequent
  idempotent runs (those counters are "present" totals, not "inserted"
  deltas) while `markets / pubs / orders / positions / ledger` counters
  do reflect inserted-only deltas (driven by `result.endswith(' 1')`).
  Operator UX cosmetic — the dataset state is unambiguously correct.
  Logged here so SENTINEL does not flag it as a bug.
* Today's P&L sums are negative for both demo users in the deterministic
  RNG seed used (-$10 / -$54). 58% win rate with symmetric
  ±0.04…±0.12 price moves and $80–$240 size variance produces a
  realistic but variance-dominated outcome at n=32 trades. Operator can
  tweak `random.Random(0x7E5D)` if a positive-leaning demo is
  preferred — current numbers still satisfy the "/pnl shows non-trivial
  numbers post-seed" done criterion.
* Demo wallet `encrypted_key` is the literal string `"DEMO_NO_KEY"` —
  only readable via direct SQL; no Telegram surface ever decodes it.
  The HD seed never derives index 999_999_xxx so there is no key
  collision risk.

No known issues affecting production code paths or activation guards.

---

## 6. What Is Next

* WARP🔹CMD review.
* WARP•SENTINEL audit (Tier STANDARD with explicit "SENTINEL REQUIRED
  before merge" directive in the task — reclassifying the SENTINEL gate
  to MAJOR-behaviour for this lane only). Audit scope:
  * Phase 0 — report at correct path, all 6 sections, state files
    updated, no `phase*/` folders, naming compliant.
  * Phase 5-equivalent — verify cleanup never touches non-demo rows
    (defence-in-depth: re-run cleanup against a DB seeded with both
    demo and non-demo records, confirm survivors).
  * Phase 1/2 — spot-check seed idempotency and exit-code contracts.
  * Phase 0 hard rule — confirm activation guards untouched
    (`ENABLE_LIVE_TRADING` / `EXECUTION_PATH_VALIDATED` /
    `CAPITAL_MODE_CONFIRMED` not referenced anywhere in the diff).
* On SENTINEL APPROVED: WARP🔹CMD merge decision.
* Post-merge operator step: run the seed against staging (or prod, per
  CMD's call) using `DEMO_SEED_ALLOW=1` + `DATABASE_URL` +
  `OPERATOR_CHAT_ID`; verify `/signals catalog` and `/dashboard` from a
  Telegram client; cleanup before any external party loses interest.

---

## Validation Tier Declaration

Tier: **STANDARD**
Rationale: introduces a new column on production tables and creates two
new operator scripts that hit the database. No runtime trading path,
no risk-gate change, no execution change — but the migration is
schema-affecting and the seed/cleanup scripts modify production data
behind env flags. The task header explicitly mandates
`SENTINEL: REQUIRED before merge`, overriding the default Tier-STANDARD
"WARP🔹CMD review only" routing.

Claim Level: **NARROW INTEGRATION**
Scope is limited to the `is_demo` flag and the seed/cleanup pair.
Telegram surfaces are NOT modified — `/signals catalog` and
`/dashboard` happen to render demo content because their existing
queries do not filter on `is_demo`, which is the desired outcome (a
demo user's view of the bot looks identical to a real user's view).

---

## NEXT PRIORITY (for PROJECT_STATE)

```
WARP•SENTINEL validation required for Lane 1C — Demo Data Seeding
before merge.
Source: projects/polymarket/crusaderbot/reports/forge/demo-seed-data.md
Tier: STANDARD (with explicit SENTINEL gate per task header)
```
