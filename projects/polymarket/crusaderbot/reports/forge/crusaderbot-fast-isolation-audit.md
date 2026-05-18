# WARP•FORGE Report — crusaderbot-fast-isolation-audit

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: user_id isolation on execution/risk/trade_engine/handlers paths; wallet startup backfill; qrcode dep removal
Not in Scope: scanner, strategy logic, signal pipeline, live trading guards, migration files, WebTrader frontend
Suggested Next Step: WARP•SENTINEL audit. Score 90+ required before merge.

---

## 1. What Was Built

Three bundled items for CRU-16 / Track J:

**FAST-ISOLATION-AUDIT**
Full audit of every DB query in domain/execution, domain/risk, services/trade_engine, and bot/handlers (position/trade ops). Result: zero isolation bugs found. All per-user queries on positions, orders, wallets, ledger, user_settings, copy_targets, copy_trade_tasks include explicit WHERE user_id = $N. Three intentional all-user queries (system-level pollers and operator cascades) were identified and marked with:
```
# INTENTIONAL: operator-scoped, all-user access — <reason>
```

**FIX-WALLET-CREATE-ON-START**
Added `backfill_missing_wallets(pool)` to `users.py`. The function runs on every app restart, finds users without a wallet row using `SELECT id FROM users WHERE id NOT IN (SELECT user_id FROM wallets)`, and calls the already-idempotent `create_wallet_for_user()` (ON CONFLICT DO NOTHING) and `seed_paper_capital()` (balance=0 + no-ledger-entry guard) for each. Failure per user is caught and logged; the loop continues. Called from `main.py:lifespan()` immediately after `seed_defaults()`. Fixes the known issue: "New users before runtime-autotrade-fix deploy still receive $0 balance."

**HOTFIX-QRCODE-DEP**
Grep confirmed zero `.py` files import `qrcode`. The comment in pyproject.toml referencing `bot/handlers/onboarding.py` is stale (the import was removed after WARP/CRUSADERBOT-HOTFIX-QRCODE-DEP but the dep was never cleaned up). Both the comment and the `qrcode[pil]>=7.4.2` line removed from pyproject.toml.

---

## 2. Current System Architecture

Pipeline unchanged:
```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
```

Isolation posture (confirmed clean):
- Every user-facing query function accepts user_id as a parameter
- Positional binding ($1, $2, ...) throughout — no string interpolation
- Dual-scoping pattern on position lookups: WHERE id=$1 AND user_id=$2
- Three intentional all-user queries marked INTENTIONAL (see section 3)

Startup sequence (main.py lifespan):
```
init_pool → run_migrations → init_cache → bootstrap_default_strategies
→ seed_defaults → backfill_missing_wallets(pool)  ← NEW
→ StrategyRegistry ready → webtrader_sse → Telegram bot start → scheduler
```

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/domain/execution/lifecycle.py` — INTENTIONAL comment on poll_once() SELECT (line ~106)
- `projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py` — INTENTIONAL comment on _cancel_pending_orders() UPDATE (line ~51)
- `projects/polymarket/crusaderbot/domain/execution/fallback.py` — INTENTIONAL comment on trigger_all_live_users() UPDATE (line ~162)
- `projects/polymarket/crusaderbot/users.py` — added backfill_missing_wallets() function (end of file)
- `projects/polymarket/crusaderbot/main.py` — added backfill_missing_wallets(pool) call in lifespan startup
- `projects/polymarket/crusaderbot/pyproject.toml` — removed qrcode[pil]>=7.4.2 + stale comment

Created:
- `projects/polymarket/crusaderbot/tests/test_user_isolation.py` — 13 hermetic tests: 3-user data segregation, ownership verification (id+user_id dual scope), 10 concurrent tasks no data bleed
- `projects/polymarket/crusaderbot/tests/test_wallet_backfill.py` — 8 hermetic tests: create on missing, idempotent (double-run), skip existing, DB failure returns 0
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-isolation-audit.md` — this file
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — updated (7 sections)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — entry appended

Intentional all-user queries audited (marked INTENTIONAL, not patched):

| File | Function | Tables | Reason |
|---|---|---|---|
| domain/execution/lifecycle.py | poll_once() | orders | System poller reads all live orders; mutations re-verify user_id from row |
| domain/risk/kill_switch_exec.py | _cancel_pending_orders() | orders | Operator kill switch cancels all pending orders |
| domain/execution/fallback.py | trigger_all_live_users() | user_settings | Operator cascade flips all live users to paper |

---

## 4. What Is Working

- All 13 tests in test_user_isolation.py pass (3-user segregation, ownership double-check, 10 concurrent tasks)
- All 8 tests in test_wallet_backfill.py pass (create, idempotent, skip existing, fail-safe)
- backfill_missing_wallets: idempotent on every restart; fail-safe on DB error; per-user failure does not abort remaining users
- qrcode[pil] removed; grep confirms zero .py imports remain
- INTENTIONAL comments mark all three all-user queries
- No changes to live trading guards, migration files, scanner, strategy logic, or signal pipeline

---

## 5. Known Issues

- Audit is hermetic (no real DB). Actual DB row counts and wallet creation cannot be verified until deployed to staging with migration 030 applied.
- test_wallet_backfill.py uses sys.modules injection to mock wallet.vault due to cryptography C-extension constraints in the local test environment. In CI (full dependency stack), the mock should be replaceable with direct patch if preferred.
- CopyTradeStrategy still reads legacy copy_targets table (separate lane, not in scope).

---

## 6. What Is Next

WARP•SENTINEL audit required. Scope:
- Verify INTENTIONAL comment placement and that no user-scoped query is incorrectly marked exempt
- Verify backfill_missing_wallets idempotency contract and startup integration
- Verify pyproject.toml is clean (no residual qrcode reference)
- Run test_user_isolation.py and test_wallet_backfill.py against full dependency stack
- Confirm no regression in existing test suite

After SENTINEL approval (score 90+): WARP🔹CMD merge decision.
