# WARP•R00T Report — smart-strike-audit-gaps-closure

Project: CrusaderBot
Project Root: projects/polymarket/crusaderbot
Branch: WARP/root-smart-strike-audit-gaps
Issue: #1801
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Status: R00T follow-up complete — R00T final gate (self-merge on CI green)
Last Updated: 2026-06-13 04:35 Asia/Jakarta

## Objective

Close the post-PR #1799 Smart Strike audit gaps with explicit tests + minor UI/observability hardening, WITHOUT expanding strategy scope or changing the user risk/reward product model. Preserve #1799 market-universe behavior and all live safety gates.

## Gaps closed

### Gap 1 — Per-user sizing isolation (explicit tests, not just audit prose)
- `test_get_live_balance_binds_only_the_active_user` (behaviour): drives `wallet.ledger.get_live_balance` with a recording fake conn — proves user A's read binds ONLY user A's `user_id` and returns A's balance; user B binds B. No cross-user/pool sum is possible.
- `test_live_ledger_filter_excludes_paper_and_pending_and_pool`: pins the live bucket SQL = confirmed-matched deposits (`ref_id` matched to `deposits`) / withdrawals / `mode='live'` positions only; asserts NO `master`/`pool`/cross-user aggregate (`SUM(w.balance`/`GROUP BY`).
- `test_gate_live_sizing_reads_only_per_user_balance_no_pool`: gate sizes from `get_live_balance(ctx.user_id)` / `ctx.live_balance_usdc`; `live_no_funds` + `live_capital_cap_exceeded` per-user; no `master_wallet`/`pool_balance`/`get_usdc_balance(` in the sizing path.
- `test_kelly_stays_fractional_quarter`: `KELLY_FRACTION == 0.25` + per-profile clamp to it.
- Paper-never-in-live: the live bucket SQL excludes paper rows (no `ref_id`) and paper positions (`mode='live'` required) — pinned above.

### Gap 2 — Polymarket-API eligibility fields + min order size
- `late_entry_v3._evaluate_market` now rejects `archived=true` (`"archived"`) and `enableOrderBook=false` (`"order_book_disabled"`) — added BEFORE the book fetch; both default-safe (reject only on explicit truthy archived / explicit false enableOrderBook), preserving existing `closed`/`active`(candle-exempt)/`acceptingOrders`/`clobTokenIds`/`tick_size`/`neg_risk`/empty-book checks. Behaviour-tested (`test_eligibility_rejects_archived_market`, `..._order_book_disabled`, `..._preserves_closed_and_accepting_checks`).
- New `LIVE_MIN_ORDER_SHARES = 5.0` (Polymarket CLOB floor) in `domain/risk/constants.py`; `live.py` fails closed pre-submit when `shares < LIVE_MIN_ORDER_SHARES` (raises `LivePreSubmitError` BEFORE `post_order`) — no ambiguous broker round-trip on a sub-minimum order. Pinned + arithmetic-tested.

### Gap 3 — Market-data freshness posture (documented + tested)
- `test_candle_scan_uses_fresh_rest_book_and_fails_closed_on_empty`: Smart Strike pulls a FRESH CLOB order book per candidate via REST (`pm.get_book` for both tokens) every scan and emits NO TRADE on an empty/missing book (`"empty_book"`) — there is no stale cached-book path that could leak a trade. On the live path, missing tick_size/neg_risk metadata fails closed (`LivePreSubmitError`). Code truth: the candle scanner does not consume a WebSocket book for entry decisions; each tick is a fresh REST pull, so the "stale WS" failure mode does not exist on this path (documented as the freshness posture).

### Gap 4 — User-facing SOL-disabled state (no UI/scanner drift)
- New shared single-source-of-truth module `domain/strategy/smart_strike_universe.py` (master/pair/timeframe resolution). The #1799 scan-gate `_smart_strike_admin_universe` now DELEGATES to it (refactor, behaviour preserved — all #1799 tests green), and the WebTrader `/autotrade` status payload resolves the SAME truth, so the picker can never present an admin-disabled market as active.
- `AutoTradeState` + `lib/api.ts` gain `smart_strike_enabled` / `smart_strike_enabled_assets` / `smart_strike_enabled_timeframes`; `get_autotrade` populates them via `smart_strike_universe.enabled_pairs()/enabled_timeframes()/master_enabled()`.
- `AutoTradePage` asset picker now `disabled`s any asset not in `smart_strike_enabled_assets` (SOL by default), renders an `n/a` marker + "unavailable — disabled by admin" title, and the toggle handler ignores disabled assets. Default selection stays BTC/ETH.
- Descriptive copy that listed SOL as an active engine asset corrected to BTC/ETH (Telegram `presets.py` + `messages.py`; WebTrader card descriptions) — "SOL admin-gated, off by default".

### Gap 5 — Observability trace expansion
- `live.py` emits one structured `live_order_intent` line carrying token id, side, shares, limit_price, best_bid/ask, tick_size, neg_risk, min_shares, size_usdc, market, user, idempotency key — every live order-intent decision is debuggable from logs alone. Pinned by `test_live_order_intent_trace_carries_decision_context`.

### Gap 6 — #1799 behavior preserved
- `_smart_strike_admin_universe` signature + return shape unchanged; all 15 #1799 universe tests + signal-scan tests stay green after the delegation refactor (the constants moved to the shared module; the one constants-location pin was repointed).

## Files Changed

- projects/polymarket/crusaderbot/domain/strategy/smart_strike_universe.py (new — shared resolver)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py (delegate gate to shared resolver)
- projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py (archived + enableOrderBook eligibility)
- projects/polymarket/crusaderbot/domain/execution/live.py (min-order fail-closed + observability trace)
- projects/polymarket/crusaderbot/domain/risk/constants.py (LIVE_MIN_ORDER_SHARES)
- projects/polymarket/crusaderbot/webtrader/backend/{router.py,schemas.py} (enabled-universe in /autotrade)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx + lib/api.ts (disabled-asset picker)
- projects/polymarket/crusaderbot/bot/handlers/presets.py + bot/messages.py (SOL copy)
- projects/polymarket/crusaderbot/tests/test_smart_strike_audit_gaps.py (new, 20 tests) + test_smart_strike_universe.py (constants pin repointed)
- state/PROJECT_STATE.md, state/WORKTODO.md, state/CHANGELOG.md

## Validation

- New `test_smart_strike_audit_gaps.py`: 20 passed. #1799 universe + signal-scan suites: green after refactor.
- Adjacent regression (smart_strike/late_entry/live/signal_scan/gate/ledger/autotrade): 897 passed.
- Full suite: **3567 passed, 11 skipped**. ruff + py_compile clean on touched Python; frontend `npm run build` green.
- Secret-pattern + UTF-8/mojibake/BOM scans clean. Branch verified from `git rev-parse`.

## Inviolable Invariants — confirmed clean

No real live order; no fund movement; no flip of `USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED`; risk constants untouched (Kelly 0.25; the new `LIVE_MIN_ORDER_SHARES` only ADDS a fail-closed floor); kill switch + `$5` live Auto-Trade gate + measured-edge policy unchanged; user risk/reward model not redesigned; Smart Strike universe stays owner-locked (no genericization); complete-set arb remains separate.

## Next Gate

WARP🔹CMD first-pass PR check → WARP•R00T final gate (R00T-assigned lane; R00T takes final gate responsibility, self-merge on CI green) — WARP•SENTINEL not run, not claimed.
