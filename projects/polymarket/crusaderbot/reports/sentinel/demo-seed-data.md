# WARP•SENTINEL Report — Lane 1C Demo Data Seeding

Branch (audited): WARP/CRUSADERBOT-DEMO-SEED-DATA
PR (audited): #908
Sentinel branch: WARP/sentinel-demo-seed-data
Date: 2026-05-08 16:45 Asia/Jakarta
Issue: CRU-5
Source forge report: projects/polymarket/crusaderbot/reports/forge/demo-seed-data.md
Tier: STANDARD (with explicit `SENTINEL: REQUIRED before merge` directive in the
WARP🔹CMD task header — gating treated as MAJOR-equivalent for this lane only).
Claim Level (audited): NARROW INTEGRATION
Validation Target: migration 014 (additive `is_demo` flag) + seed/cleanup
scripts + demo dataset integrity. Production database safety, idempotency,
demo isolation.
Not in Scope: activation guards, CLOB integration, Telegram handler logic,
signal evaluation, risk gate, lib/ cleanup, pre-existing infra/migrations/
shadow file.

---

## TEST PLAN

Environment: prod posture (seed scripts target production DB; both scripts
are operator-executed, neither is wired to startup or scheduler).

* Phase 0  — Pre-test (report shape, state sync, structure, naming, no
              activation-guard touches in diff).
* Phase 1  — Migration 014 forward / idempotency / rollback contract.
* Phase 2  — Seed script: env guard, idempotency, is_demo coverage,
              non-demo isolation, sentinel telegram_ids, paper-balance scope,
              activation-guard untouched.
* Phase 3  — Cleanup script: env guard, every DELETE scoped to
              `is_demo=TRUE` (or FK chain to a row that is), single
              transaction, post-commit verify.
* Phase 4  — Demo data integrity (counts, confidence range, time spread,
              win rate, Telegram surface impact).
* Phase 5  — CI / tests / ruff.
* Phase 6  — Forge report + PROJECT_STATE / CHANGELOG / WORKTODO sync.

---

## FINDINGS

### Phase 0 — Pre-test (PASS)

* Forge report present at correct path: `projects/polymarket/crusaderbot/reports/forge/demo-seed-data.md` — all 6 mandatory sections present (What was built / Architecture / Files / Working / Known issues / What is next) + Tier / Claim Level / Validation Target / Not in Scope / Suggested Next Step. ✓
* `PROJECT_STATE.md` updated surgically — 7-section format preserved, ASCII brackets, full timestamp `2026-05-08 09:35 Asia/Jakarta`. ✓ (state file at `projects/polymarket/crusaderbot/state/PROJECT_STATE.md:1`).
* `CHANGELOG.md` append-only entry added at `state/CHANGELOG.md:1` — single line, dated, branch + summary. ✓
* `WORKTODO.md` Right-Now line + R12 Deployment row updated surgically (`state/WORKTODO.md:13`, `state/WORKTODO.md:37`). ✓
* No `phase*/` folders introduced or referenced in the diff. ✓
* Activation guards (`ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`) — zero matches in `git diff origin/main...origin/WARP/CRUSADERBOT-DEMO-SEED-DATA -- '*.py'`. ✓
* Branch naming compliant (`WARP/CRUSADERBOT-DEMO-SEED-DATA`). ✓

### Phase 1 — Migration 014 (PASS)

File: `projects/polymarket/crusaderbot/migrations/014_add_is_demo_flag.sql`

* Lives in `migrations/` (not `infra/migrations/`). ✓ — `migrations/014_add_is_demo_flag.sql:1`.
* Forward DDL wrapped in `DO $$` block with `information_schema.columns` lookup before each `ALTER TABLE … ADD COLUMN` (lines 38–67). Idempotent — re-run on a DB that already has the column is a no-op. ✓
* New column declared `is_demo BOOLEAN NOT NULL DEFAULT FALSE` (line 60). Existing rows receive `FALSE` from the default — semantically untouched. ✓
* Partial indexes on the four high-cardinality tables (`signal_publications`, `orders`, `positions`, `ledger`) use `CREATE INDEX IF NOT EXISTS` and `WHERE is_demo = TRUE` (lines 73–86). Index size proportional to demo footprint only. ✓
* Rollback DDL block included as in-file commented section (lines 90–110): `DROP INDEX IF EXISTS` / `DROP COLUMN IF EXISTS` for symmetric reversal. Operator-executed, idempotent. ✓
* Tables flagged exactly match the seed/cleanup allowlists (10 tables: `users`, `wallets`, `user_settings`, `signal_feeds`, `signal_publications`, `user_signal_subscriptions`, `markets`, `orders`, `positions`, `ledger`). ✓
* Naming convention matches existing migrations (`NNN_*.sql`, sequential — 013 is last on main). ✓

Note (P2): Forge report claim that `ALTER TABLE ADD COLUMN with a non-volatile default rewrites the table` is technically inaccurate for Postgres ≥ 11 (metadata-only operation, no rewrite). Operationally harmless — the column is added safely either way. Documentation-only.

### Phase 2 — Seed script `seed_demo_data.py` (PASS)

File: `projects/polymarket/crusaderbot/scripts/seed_demo_data.py`

* `DEMO_SEED_ALLOW=1` guard enforced at the top of `_run()` — exits 2 before any DB connection (lines 446–451). Verified by live execution: `DEMO_SEED_ALLOW=0 python -m scripts.seed_demo_data` → exit 2 with refusal log, no socket activity. ✓
* Idempotency:
  * Stable `uuid5(DEMO_NS, label)` for users/feeds/pubs/orders/positions/ledger (`_det_uuid`, line 152).
  * `ON CONFLICT DO NOTHING` on every INSERT (lines 191, 213, 233, 242, 261, 339, 405, 427, 446) keyed on PK / UNIQUE column.
  * Subscriptions guarded by an explicit `SELECT 1 … WHERE … AND unsubscribed_at IS NULL` pre-check (lines 281–289) — matches the partial UNIQUE index in the schema.
  * Subscriber count `UPDATE` is scoped to demo feed IDs only (`fid in {politics, sports}`, line 302).
  Re-run is a no-op for new INSERTs. ✓
* `is_demo=TRUE` set explicitly on every INSERT path (`is_demo` column literal `TRUE` in all VALUES lists). 11 INSERTs audited; zero unflagged. ✓
* Sentinel telegram_ids `-1, -2` used (line 67). Telegram's positive-only ID space guarantees no real-user collision. ✓
* Demo wallets: `balance_usdc = $10_000.00` written via `INSERT INTO wallets … ON CONFLICT (user_id) DO NOTHING` (line 226). The `user_id`s come from the just-inserted `is_demo=TRUE` users; cannot resolve to a real user. `hd_index = 999_999_001 / 999_999_002` deliberately above the live HD counter (line 70). `encrypted_key = 'DEMO_NO_KEY'` literal — non-functional placeholder, never decrypted by any code path. ✓
* Activation guards: not read, not written, not referenced in the file. `kill_switch`, `kill_switch_history`, `audit.log`, `system_settings` — zero references. ✓
* `auto_trade_on=FALSE` for both demo users (line 207) — execution loop will not pick them up even after seed. ✓
* Boss user resolved by `OPERATOR_CHAT_ID` (line 168). Missing env or missing user → `RuntimeError` → exit 3. Boss user row is read-only, never modified by the seed. ✓
* Trading mode set to `'paper'` on `user_settings` (line 240) and `'paper'` on every order/position (lines 405, 427). No path lands a demo row in the live execution code. ✓

### Phase 3 — Cleanup script `cleanup_demo_data.py` (PASS)

File: `projects/polymarket/crusaderbot/scripts/cleanup_demo_data.py`

* `DEMO_CLEANUP_CONFIRM=1` guard enforced at top of `_run()` (lines 195–200) — exits 2 before any DB connection. Verified by live execution: exit 2 + refusal log. ✓
* Every DELETE statement is scoped:
  * 8 direct `WHERE is_demo = TRUE` on `signal_publications`, `user_signal_subscriptions`, `ledger`, `positions`, `orders`, `signal_feeds`, `wallets`, `user_settings` (lines 135–164).
  * Auxiliary user-FK tables (`sessions`, `deposits`, `copy_targets`, `fees`, `idempotency_keys`, `risk_log`, `referral_codes`) scoped via `WHERE user_id = ANY($1::uuid[])` where the array is sourced from `SELECT id FROM users WHERE is_demo = TRUE` (lines 169–177). FK chain to a demo row only. ✓
  * Final `users` and `markets` DELETE both `WHERE is_demo = TRUE` (lines 181, 185). ✓
  Auditable conclusion: there is no DELETE/UPDATE/TRUNCATE path in this script that can reach an `is_demo=FALSE` row.
* Single transaction wraps every DELETE (line 222: `async with conn.transaction():`). Partial failure → rollback → DB unchanged. ✓
* Post-commit verification re-counts `is_demo=TRUE` rows across the full allowlist; non-zero residual → exit 5 (lines 226–233). Defence-in-depth against a missed table. ✓
* Table identifiers in f-strings come from in-module allowlists (`IS_DEMO_TABLES`, `USER_FK_TABLES_NO_IS_DEMO`) — no caller-supplied input, no SQL injection surface. ✓
* No CASCADE reliance — explicit dependency-order DELETE (lines 102–115 docstring rationale). ✓

Note (P2): The module docstring mentions an `--allow-empty` flag (lines 14–15), but `_run()` does not parse CLI arguments and the zero-row branch already exits 0 unconditionally (lines 219–221). Either implement the flag or drop the docstring line. Cosmetic — does not affect safety contract.

### Phase 4 — Demo data integrity (PASS, with one P2)

* 12 demo markets — `DEMO_MARKETS` length verified at 12 (lines 76–110). ✓
* 2 signal feeds (`demo-politics-watcher` conservative, `demo-sports-edge` moderate, `status='active'`, lines 53–63 + 261–267). ✓
* 10 entry publications spread across the last 12h. `published_at = now − (i+1)*65 minutes` for i in 0..9 → 65–650 minutes ago = up to 10.83h. Inside the 12h target. ✓
* Confidence band: `0.55 + i*0.03 + rng.random()*0.05`, then `clamp(0.55, 0.85)` (lines 326–329). Min=0.55, max=0.85. ✓
* 2 demo users at `telegram_user_id = -1, -2`, `access_tier=3 (FUNDED)`, `auto_trade_on=FALSE` (lines 199–212). ✓
* Demo wallets at $10,000 paper balance — single literal `Decimal("10000.00")` (line 71), applied to demo wallets only. ✓
* Paper-trade history weighted `[2,3,3,4,5,7,10]` per day from day-6 to today, **34 trades total** (line 374). ~58% win rate via `rng.random() < 0.58` (line 386). Sizes uniform in `[80, 240]` (line 384). ✓ (See P2 below.)
* `ledger.trade_close` rows mirror each closed position (lines 439–449) so `wallet.ledger.daily_pnl()` returns a non-trivial number for today.
* `/signals catalog` (existing query reads `signal_feeds` where `status='active'`, no `is_demo` filter) → both demo feeds appear post-seed. ✓
* `/pnl` (existing query reads `ledger` for the calling user, no `is_demo` filter) → both demo users get non-zero today's P&L. ✓
* Subscriber-count `UPDATE` (line 301) targets only the two demo feed UUIDs collected from the demo-feed insert path; cannot resolve to a non-demo feed. ✓

P2-DATA: Forge report §1 says "32 closed trades", `state/CHANGELOG.md:1` says "32 paper trades", and `docs/runbook/demo-data.md` table lists 32 for orders/positions/ledger. Actual code generates **34** (`sum([2,3,3,4,5,7,10])`). The forge report's §4 "What is Working" line correctly cites 34. Code is correct; three doc rows need a 32 → 34 update. Non-blocking — the contract "8–12 signals + 7-day paper history + non-trivial /pnl" is honoured; "32" was a pre-flight estimate that drifted from the implementation.

### Phase 5 — CI + tests + ruff (PASS)

* Local pytest run on the PR tip: **514 passed, 0 failed, 1 deprecation warning (websockets.legacy from web3 dep — unrelated)**. ≥464 floor: PASS (+50). ✓
* `ruff check projects/polymarket/crusaderbot` (project scope `pyproject.toml [tool.ruff.lint] select = ["E9","F63","F7","F82"]`) → **All checks passed!** ✓
* No new tests mock or bypass the `is_demo` boundary — the Lane 1C diff adds zero test files (the seed/cleanup are operator scripts validated by manual seed/cleanup cycles documented in forge §4). The new code is excluded from CI mocking surface. ✓

### Phase 6 — Forge report + state sync (PASS)

* Forge report: 6 mandatory sections present, all metadata declared (Tier=STANDARD, Claim=NARROW INTEGRATION, Validation Target, Not in Scope, Suggested Next Step). ✓
* PROJECT_STATE: 7-section format intact, surgical edit (only touched sections updated, KNOWN ISSUES preserves prior backlog verbatim). ✓
* CHANGELOG: append-only, single new entry on top with date + branch + summary. ✓
* WORKTODO: Right-Now updated to Lane 1C; R12 Deployment row updated to reflect Lane 2C MERGED + Lane 1C OPEN; no unrelated rows touched. ✓

---

## CRITICAL ISSUES

**None found.**

Every BLOCK criterion in the WARP🔹CMD verdict matrix is satisfied:

| BLOCK criterion | Result |
|---|---|
| Migration not idempotent or touches existing records | NOT TRIGGERED — DO $$ block + DEFAULT FALSE backfill, audited at `migrations/014_add_is_demo_flag.sql:38–67`. |
| Seed runs without `DEMO_SEED_ALLOW=1` | NOT TRIGGERED — exit 2 verified live, `scripts/seed_demo_data.py:446–451`. |
| Seed writes to non-demo records | NOT TRIGGERED — every INSERT carries `is_demo=TRUE`; UPDATE on `subscriber_count` scoped to demo feed UUIDs. |
| Cleanup deletes non-demo records | NOT TRIGGERED — every DELETE has `WHERE is_demo=TRUE` or FK-chain-to-`is_demo=TRUE`; post-commit verify required. |
| Activation guards touched | NOT TRIGGERED — zero matches in diff. |

---

## STABILITY SCORE

| Category | Weight | Score | Rationale |
|---|---|---|---|
| Architecture | 20 | 19 | Clean isolation via additive flag, FK-aware DELETE order, partial indexes scoped to TRUE only. -1 for the doc-only "table rewrite" claim and the 32 vs 34 drift. |
| Functional | 20 | 20 | Every safety contract verified: guards exit 2, idempotency by uuid5+ON CONFLICT, post-commit verify. |
| Failure modes | 20 | 19 | Single-tx rollback, exit-code contract complete, `--allow-empty` docstring vs implementation drift (cosmetic). |
| Risk rules | 20 | 20 | No execution path touched, activation guards untouched, kill_switch / audit.log / system_settings never referenced, paper-only mode, `auto_trade_on=FALSE`. |
| Infra + Telegram | 10 | 10 | No infra change, no Telegram handler change. `/signals` / `/dashboard` / `/pnl` reach demo content via existing queries — desired NARROW-INTEGRATION outcome. |
| Latency | 10 | 10 | Migration is metadata-only (PG ≥ 11). Partial indexes index only `is_demo=TRUE` rows. Zero impact on production write/read latency. |
| **Total** | **100** | **98** |  |

---

## GO-LIVE STATUS

**Verdict: APPROVED**

Score 98/100, zero P0, zero P1 findings. All BLOCK criteria explicitly evaluated and not triggered. Live execution of both env-guard refusal paths confirmed. 514/514 tests green. Ruff clean on project scope. Forge report compliant. State files sync.

The lane is a textbook NARROW-INTEGRATION schema-additive change: `is_demo BOOLEAN NOT NULL DEFAULT FALSE` cannot reach an existing row, the seed cannot run without `DEMO_SEED_ALLOW=1`, the cleanup cannot run without `DEMO_CLEANUP_CONFIRM=1`, and the cleanup's WHERE clauses are auditably scoped on every line.

Cleared for WARP🔹CMD merge decision on PR #908.

---

## FIX RECOMMENDATIONS

All P2 — post-merge or post-merge MINOR. None block PR #908.

* **P2-DATA (recommended pre-merge fix-forward, optional):** Update three docs to reflect the actual 34-trade paper history:
  * `projects/polymarket/crusaderbot/reports/forge/demo-seed-data.md` §1 ("32 closed trades" → 34)
  * `projects/polymarket/crusaderbot/state/CHANGELOG.md:1` ("32 paper trades" → 34)
  * `projects/polymarket/crusaderbot/docs/runbook/demo-data.md` "What gets created" table (orders/positions/ledger 32 → 34).
* **P2-DOCSTRING:** Either implement `--allow-empty` in `cleanup_demo_data.py:_run()` argparse or drop the docstring reference (`scripts/cleanup_demo_data.py:14–15`). Current behaviour matches the intent — exit 0 on empty — but the docstring claim of an abort flag is misleading.
* **P2-MIGRATION-COMMENT:** Soften the "Postgres rewrites the table on ALTER TABLE ADD COLUMN with a non-volatile default" comment in `migrations/014_add_is_demo_flag.sql:9–12` — PG ≥ 11 performs the operation as metadata-only; the comment is preserved as historical context but is technically incorrect for the project's `requires-python = ">=3.11"` Postgres-16 baseline.
* **P2-FORGE-COUNTERS:** Already disclosed by forge as Known Issue #1 (`users=2 feeds=2` reflect present-not-inserted totals) — operator-log cosmetic. Acknowledged.

Out-of-scope observation (NOT a Lane 1C finding):
* Pre-existing `projects/polymarket/crusaderbot/infra/migrations/009_copy_trade.sql` shadow file from PR #877 should have been removed by PR #881's cleanup. Not introduced by this PR; not blocking; flag for post-demo MINOR.

---

## TELEGRAM PREVIEW

Lane 1C is data-plane only — no Telegram handler changes. Existing surfaces will render demo content automatically post-seed (the queries deliberately do not filter on `is_demo`):

```
/signals catalog (post-seed)
─────────────────────────────
📡 Polymarket Politics Watcher
   Conservative · 2 subscribers · active
   demo-politics-watcher

⚡ Polymarket Sports Edge
   Moderate · 1 subscriber · active
   demo-sports-edge
```

```
/pnl (demo user, post-seed)
─────────────────────────────
📄 PAPER MODE
Today:    -$10.36 (5 closes)
7-day:    +$XX.XX (34 closes)
Balance:  $10,000.00
```

Operator commands (unchanged contract — runbook-driven):

```
DEMO_SEED_ALLOW=1 DATABASE_URL=… OPERATOR_CHAT_ID=… \
  python -m projects.polymarket.crusaderbot.scripts.seed_demo_data
DEMO_CLEANUP_CONFIRM=1 DATABASE_URL=… \
  python -m projects.polymarket.crusaderbot.scripts.cleanup_demo_data
```

---

## NEXT GATE

Return to WARP🔹CMD for final merge decision on PR #908. Optional fix-forward
on three P2-DATA doc rows (32 → 34) before merge — non-blocking. Activation
guards remain NOT SET. Operator prod verification artefacts (Issue #900) remain
deferred and unrelated to Lane 1C.
