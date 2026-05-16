# WARP•FORGE Report — runtime-autotrade-fix

**Branch:** WARP/CRUSADERBOT-RUNTIME-AUTOTRADE-FIX
**Date:** 2026-05-16 21:13 Asia/Jakarta
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** New-user $1K paper seed, market scanner liquidity floor, exit_watcher MARKET_EXPIRED guard
**Not in Scope:** EDGE_PRICE_THRESHOLD retune, notification granularity backend ext (#1069), live trading activation, any migration
**Suggested Next Step:** WARP🔹CMD review → merge. Then: EDGE_PRICE_THRESHOLD retune after post-fix signal data.

---

## 1. What Was Built

Three tightly-coupled fixes to the "new user → productive paper trade" flow:

**Fix 1 — Atomic $1,000 paper seed on user creation**
- Added `seed_paper_capital(user_id)` to `users.py`: atomic PostgreSQL transaction with `FOR UPDATE` row lock, double-guards via wallet balance check and ledger dedup check. Idempotent — safe to retry.
- Called from `upsert_user()` in the `_is_new_user` branch, after `create_wallet_for_user()`. Wrapped in independent try/except so wallet-creation failures and seed failures are isolated and logged.
- Existing seed paths in `bot/handlers/start.py:get_started_cb` and `bot/handlers/onboarding.py:_start_cb` preserved as defense-in-depth.

**Fix 2 — Raise MIN_LIQUIDITY to $10K**
- `MIN_LIQUIDITY: float = 1_000.0` → `10_000.0` in `jobs/market_signal_scanner.py`.
- Eliminates illiquid long-shot markets (Austria FIFA, Cape Verde FIFA) with no Gamma orderbook depth from entering the edge-finder pipeline.

**Fix 3 — Verify resolved status before MARKET_EXPIRED**
- Added `_market_actually_expired(market_id)` helper to `domain/execution/exit_watcher.py`: queries `markets.resolved` and `end_date_iso`; returns True only when verifiably resolved or past end date.
- Added `datetime`, `timezone` import and `get_pool` import to exit_watcher.
- Replaced unconditional `_close_expired_position` call after `_EXPIRED_TICK_THRESHOLD` None ticks with a DB-verified check. Stale-price path logs a warning and pins the counter at threshold (no unbounded growth); resolved-market path closes as before.
- Phase B (`list_open_on_resolved_markets`) unchanged — remains canonical resolved-market sweep.

---

## 2. Current System Architecture

```
Telegram → bot/handlers/* → upsert_user() → create_wallet_for_user()
                                          → seed_paper_capital() [NEW — primary seed path]
                                          → get_started_cb / _start_cb [defense-in-depth]

Scheduler → market_signal_scanner.run_job()
            → polymarket.get_markets()
            → liq < MIN_LIQUIDITY(10K) → skip [RAISED]
            → edge_finder → _publish()

Scheduler → exit_watcher.run_once()
  Phase A: list_open_for_exit()
           → _fetch_live_price() → None × N
           → fail_count >= _EXPIRED_TICK_THRESHOLD
           → _market_actually_expired() [NEW GATE]
               resolved=True OR end_date < now → _close_expired_position()
               else → log warning, pin counter, continue
  Phase B: list_open_on_resolved_markets() → _close_expired_position() [unchanged]
```

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/users.py` — added `seed_paper_capital()`, updated `upsert_user()`, added `logging` import
- `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py` — `MIN_LIQUIDITY` 1K→10K
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` — `_market_actually_expired()`, updated fail-count block, `datetime`/`timezone`/`get_pool` imports

**Created:**
- `projects/polymarket/crusaderbot/tests/test_users.py` — 5 tests
- `projects/polymarket/crusaderbot/tests/test_market_signal_scanner.py` — 2 tests
- (appended) `projects/polymarket/crusaderbot/tests/test_exit_watcher.py` — 3 new tests (+`_make_pool_for_market` helper)

---

## 4. What Is Working

- `seed_paper_capital` idempotent: zero-balance guard + ledger dedup guard both verified by test.
- `upsert_user` new-user path verified end-to-end by test with wallet creation + seed.
- Scanner liquidity floor raised: markets with `liquidity=5_000` produce zero `_publish` calls.
- `_market_actually_expired` correctly gates close on `resolved=True`, `resolved=False+past end_date`, and does NOT close on `resolved=False` (pins counter instead).
- All 10 new tests pass. ruff clean on all modified files.
- Paper guards untouched: `ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED` all remain false.

---

## 5. Known Issues / Follow-ups

- `EDGE_PRICE_THRESHOLD = 0.15` left unchanged — retune requires post-fix signal data; separate lane.
- Notification granularity backend extension (deferred from PR #1069) — separate lane.
- `seed_paper_capital` depends on `create_wallet_for_user` completing first; if wallet creation fails, seed logs an exception and returns False on next call (wallet row absent path). No automatic retry beyond the next `/start` or `get_started_cb` call.
- Two existing $0 users (`qwneer8`, `Maver1ch69`) already backfilled via SQL — no migration needed.
- End-to-end live verification (`/start` fresh account → Balance: $1,000`) requires WARP🔹CMD execution on Fly machine.

---

## 6. What Is Next

- WARP🔹CMD merge decision (STANDARD tier — no SENTINEL required).
- Post-merge: `/start` verification from a fresh Telegram account on Fly.io.
- Post-merge: auto-trade enabled → confirm at least one position stays open >5 min without false `market_expired`.
- Sentry: confirm no new `NotNullViolationError` on `wallets.deposit_address`; no new `market_expired` spam.
- Follow-up lane: `EDGE_PRICE_THRESHOLD` retune against post-fix data.
