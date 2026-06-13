# WARP•R00T — clob-micro-live-open-order-path (#1817)

Branch: `WARP/clob-micro-live-open-order-path`
Issue: #1817
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Role: WARP•R00T (docs-aligned verification + explicit preflight matrix + narrow runbook)
Date: 2026-06-13 12:34 Asia/Jakarta

Validation Target: confirm the bot has a docs-aligned, minimal CLOB live open-order path for one guarded micro trade with every preflight blocker the issue lists fail-closed; add an explicit single-table preflight matrix test; document the operator runbook.

Not in Scope (per issue): no native USDC/USDT enablement, no Bridge/pUSD architecture change, no strategy threshold tuning, no order spam, no scale-up, no market-family expansion, no real fund movement, no bypass of live guards, no secrets in repo/logs/reports/fixtures.

---

## 1. Verdict

**Code path is already production-grade — no new live-order code is needed.** Per the recent #1814 go-live-readiness audit and an independent #1817 verification pass against `domain/execution/live.py`, `domain/risk/gate.py`, `integrations/clob/*`, and `wallet/ledger.py`, **every** preflight blocker the issue lists is checked and fail-closed before any CLOB POST. The remaining gap is operational — the runbook in `reports/forge/go-live-readiness.md` already covers it.

This lane therefore lands the two things the issue explicitly asks for under §8 ("if the code already has a valid open-order path and only production ops are missing, do not overbuild"):

1. **A docs-aligned mapping** of the existing path to each Polymarket CLOB doc URL the issue cites (§3 below).
2. **An explicit issue-#1817 preflight matrix test** (`tests/test_clob_micro_live_preflight.py`, 17 tests) that pins each preflight blocker as one parametrised table so CMD can audit the safety chain end-to-end from one file.

No runtime code, no risk constant, no live-guard flag, no migration touched. No real fund movement.

## 2. The existing live open-order path (code-truth)

End-to-end shape, with file:line evidence:

1. **Router gate.** `domain/execution/router.py` — checks the GLOBAL DB toggle (`is_global_live_enabled`, fail-safe to paper) and the per-call guard chain BEFORE entering the live engine. `LivePreSubmitError` -> audited paper fallback. `LivePostSubmitError` -> NO paper fallback (would duplicate an on-chain order) + operator page.
2. **Activation guard chain.** `domain/execution/live.py:60-90` `assert_live_guards(role, trading_mode)` raises `LivePreSubmitError` unless ALL of: `ENABLE_LIVE_TRADING`, `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED`, `RISK_CONTROLS_VALIDATED`, `SECURITY_HARDENING_VALIDATED`, `USE_REAL_CLOB`, plus `role=='admin'` and `trading_mode=='live'`.
3. **Guard-bypass detection (defense-in-depth).** `live.py:127-145` logs CRITICAL if `execute()` is entered with incomplete guards before `assert_live_guards` runs.
4. **Dry-run intercept.** `live.py:147-157` — `USE_REAL_CLOB=True` + `ENABLE_LIVE_TRADING=False` -> logs the intent and returns `{"status": "dry_run", "mode": "paper"}` with **no DB write, no broker call**. This is the credential-proof path the issue's preflight requires.
5. **Idempotency-on-submit.** `live.py:165-183` early `SELECT id FROM orders WHERE idempotency_key=$1`; `live.py:318-332` `INSERT INTO orders (..., status='pending') ON CONFLICT (idempotency_key) DO NOTHING RETURNING id`. A retry on the same key returns `{"status": "duplicate", "mode": "live"}` before any CLOB POST.
6. **CLOB market metadata preflight.** `live.py:185-205` fetches `tick_size` + `neg_risk` via `MarketDataClient`; any failure raises `LivePreSubmitError("CLOB market metadata unavailable")` so a wrong-tick order is impossible.
7. **Slippage fence.** `live.py:223-236` `SLIPPAGE_GUARD_PCT = 0.05` (5%). `abs(limit_price - signal_price) / signal_price > 0.05` -> `LivePreSubmitError("SLIPPAGE_REJECTED")` BEFORE any broker call.
8. **Min-order-shares floor.** `live.py:243-248` `LIVE_MIN_ORDER_SHARES = 5` (`domain/risk/constants.py:54`). `shares = size_usdc / limit_price`; `shares < 5` -> `LivePreSubmitError("below CLOB minimum")`.
9. **CLOB client construction.** `live.py:271-316` — when `USE_PER_USER_EXECUTION` is on, the per-user client is resolved with a wallet-identity assertion (drift -> `LivePreSubmitError`). Default uses the global singleton.
10. **Order backend (sidecar precedence).** `integrations/clob/__init__.py:get_clob_client` — `USE_RUST_SIDECAR=True` selects `RustSidecarClient` (the ONLY backend that signs POLY_1271 / EIP-1271 deposit-wallet orders), else `ClobV2Client` (py-clob-client-v2 v1.0.1, native v2 order struct), else `ClobAdapter` (REST), else `MockClobClient`.
11. **Order submission.** `live.py:345-354` `client.post_order(token_id, side="BUY", price=limit_price, size=shares, order_type=order_type, tick_size=_tick_size, neg_risk=_neg_risk)`. The interface mirrors the v2 SDK shape; `order_type` supports `GTC` / `FOK` / `FAK`.
12. **Pre/post-submit error split.** `ClobAuthError` -> `LivePreSubmitError` (definitively pre-submit, router may paper-fallback). Any other exception -> ambiguous: `UPDATE orders SET status='unknown'`, operator page, `LivePostSubmitError` (router REFUSES to paper-fallback).
13. **Position persistence + ledger debit.** `live.py:402-430` atomic `UPDATE orders SET status='submitted', polymarket_order_id=...` + `INSERT INTO positions (..., mode='live', status='open')` + `ledger.debit_in_conn(T_TRADE_OPEN)`.
14. **Notification.** `live.py:457-474` `_notifier.notify_entry()` (Telegram + persisted web alert via the existing dedup-by-tx path); fail-soft so a notification outage cannot poison the order. Pre-submit failures audit `live_pre_submit_failed`; ambiguous submits audit `live_submit_ambiguous` + operator Telegram alert.

## 3. Polymarket docs → repo evidence mapping

Each Polymarket doc URL the issue cites mapped to the file:line that satisfies it.

| Polymarket doc | Repo evidence |
|---|---|
| https://docs.polymarket.com/api-reference/authentication (L1 + L2 layered auth) | `integrations/clob/auth.py` (L1 EIP-712 signer + L2 HMAC headers), `integrations/clob/user_client.py` (per-user credential derivation), `integrations/clob/v2_client.py:_ensure()` (lazy SDK build under lock) |
| https://docs.polymarket.com/trading/quickstart | `domain/execution/live.py:93-476` (the minimal submit shape — token_id, side, price, size, order_type, tick, neg_risk) + `assert_live_guards` |
| https://docs.polymarket.com/trading/orders/create (sign EIP-712, submit signed order) | Bot delegates to the chosen backend's `post_order()` (`integrations/clob/v2_client.py` for v2 SDK; `integrations/clob/rust_sidecar.py` for POLY_1271). Bot never hand-rolls L1 signing inline — uses the SDK / sidecar so docs-aligned changes upstream propagate. |
| https://docs.polymarket.com/trading/clients/l2 (`createAndPostOrder`, `createAndPostMarketOrder` semantics) | `live.py:345-354` -> `client.post_order(order_type="GTC"|"FOK"|"FAK")`. GTC = limit/post-rest; FOK = fill-or-kill; FAK = fill-and-kill. The same `order_type` parameter feeds the v2 SDK's `create_and_post_order` / `create_and_post_market_order` shape. |
| https://docs.polymarket.com/concepts/order-lifecycle | `orders` table (migration 001+ amendments) has `mode/status/idempotency_key/polymarket_order_id/error_msg`. `live.py:318-432` walks the lifecycle: `pending` -> `submitted` -> failed/unknown branches handled atomically. |
| https://docs.polymarket.com/api-reference/trade/post-a-new-order | `client.post_order()` interface (above). FOK/FAK/GTC all routed via `order_type`. |
| https://docs.polymarket.com/api-reference/market-data/get-order-book | TOB freshness gate in `services/signal_scan/signal_scan_job.py:2524-2570` (`TOB_STALE_MS` reject); `best_ask`/`best_bid` flow into `compute_aggressive_limit_price`. The live order intent carries an explicit fresh-book guarantee per #1801. |
| https://docs.polymarket.com/api-reference/market-data/get-tick-size | `MarketDataClient.get_tick_size(token_id)` in `live.py:185-205` (fail-closed `LivePreSubmitError` on absence). |
| https://docs.polymarket.com/api-reference/markets/get-clob-market-info | `live.py:185-205` also fetches `neg_risk` for the correct Exchange contract selection. |
| https://docs.polymarket.com/trading/deposit-wallets (POLY_1271 / signature type 3) | Rust sidecar is the authoritative deposit-wallet path (proven from Fly per #1814 — `sidecar-clob-url` PROOF=PASS, sig_type=3, allow_fills=false, cancel confirmed). py-clob-client-v2 cannot sign POLY_1271 (upstream #70). |

The bot deliberately uses the SDK / sidecar rather than hand-rolling raw REST signing, matching the issue's docs guidance ("SDK path is preferred for minimal implementation").

## 4. Preflight matrix (the issue's blocker list — every row pinned)

New file `tests/test_clob_micro_live_preflight.py` — 17 tests in one parametrised table. Each test maps to a row in the issue's preflight list:

| Issue blocker | Test | Fail mode pinned |
|---|---|---|
| User must be in LIVE mode | `test_preflight_user_must_be_in_live_mode` | `LivePreSubmitError("trading_mode=paper")` |
| Role must be admin | `test_preflight_role_must_be_admin` | `LivePreSubmitError("not admin")` |
| 6 env guards (each in isolation) | `test_preflight_each_env_guard_fails_closed[*]` (parametrised x6) | `LivePreSubmitError("<FLAG_NAME>")` |
| CLOB credentials present + dry-run proof | `test_preflight_dry_run_when_use_real_clob_but_live_trading_off` | Returns `{"status":"dry_run","mode":"paper"}`; **no DB write, no broker call** |
| CLOB auth fails before submit | `test_preflight_clob_auth_error_classified_pre_submit` | `LivePreSubmitError("prepare failed")` (router-safe paper fallback) |
| Tick size loaded / price rounded correctly | `test_preflight_tick_size_unavailable_fails_closed` | `LivePreSubmitError("CLOB market metadata unavailable")`; `post_order` not called |
| Min order size satisfied | `test_preflight_below_min_order_shares_fails_closed` | `LivePreSubmitError("below CLOB minimum")`; `post_order` not called |
| Slippage ≤ 5% pre-submit | `test_preflight_slippage_above_5pct_fails_closed` | `LivePreSubmitError("SLIPPAGE_REJECTED")`; `post_order` not called |
| Idempotent replay -> no double POST | `test_preflight_idempotent_replay_does_not_double_submit` | Returns `{"status":"duplicate","mode":"live"}`; `post_order` not called |
| Live balance excludes paper / pending / reserved / withdraw-pending | `test_live_ledger_filter_excludes_non_live_money` | Pins the `live_ledger_filter_sql` predicate; asserts the forbidden tokens (`reserved_for_order`, `withdraw_pending`, paper modes) are NOT admitted |
| Never full Kelly + risk constants frozen | `test_kelly_constant_is_quarter_and_capped` | `KELLY_FRACTION == 0.25`, `SLIPPAGE_GUARD_PCT == 0.05`, `LIVE_MIN_ORDER_SHARES == 5` |
| Hermeticity invariant (no real CLOB call in CI) | `test_no_real_clob_call_in_this_test_module` | Source-pin: no import of v2/adapter/sidecar / aiohttp; every `execute()` call must go through the patched `_run` helper |

The kill-switch ON, Auto-Trade OFF, balance < $5, market-not-eligible, and stale-orderbook blockers live in the risk gate (`domain/risk/gate.py` steps 1, 2, 11, 13, 15) and at the scan TOB freshness gate (`signal_scan_job.py:2524-2570`); their existing test files (`test_kill_switch_paths.py`, `test_live_gate_hardening.py`, `test_live_cap_shared.py`, `test_tob_freshness_gate.py`) pin those — this matrix complements them without duplicating.

## 5. Narrow proof-run runbook (single micro-trade)

The full step-by-step go-live runbook lives in `reports/forge/go-live-readiness.md` (sidecar wiring -> 6-guard sequence -> per-user opt-in + USDC.e funding -> funded micro-trade -> halt/rollback). For #1817 the operator-facing single-micro-trade proof is:

1. **Credential / dry-run proof (NO funds at risk).** With sidecar wired, set `USE_REAL_CLOB=true` while keeping `ENABLE_LIVE_TRADING=false`. Confirm at boot: `clob: POLY_1271 deposit wallet resolved=…, creds derived`. Trigger a `late_entry_v3` candidate against BTC/ETH 5m/15m; confirm a `live.execute dry_run` log line carrying `token_id`, `side`, `shares`, `price`, `order_type`, `idempotency_key`. There must be NO INSERT INTO orders for this tick.
2. **Guard sequence.** In order: `RISK_CONTROLS_VALIDATED=true` → `SECURITY_HARDENING_VALIDATED=true` → `EXECUTION_PATH_VALIDATED=true` → `CAPITAL_MODE_CONFIRMED=true` → `ENABLE_LIVE_TRADING=true` → `system_settings.global_live_trading_enabled='true'`. Per-user: role `admin`, `trading_mode='live'` via typed-CONFIRM (Auto-Trade is force-OFF on the switch by design).
3. **Fund with the smallest viable USDC.e.** Deposit enough that `get_live_balance >= $5` and the smallest possible `late_entry_v3` candidate clears step 14's `LIVE_MIN_ORDER_SHARES=5` (at typical favored prices ~$0.55 that means ~$3 of room at the bottom — fund $10-20 USDC.e for the first proof). Send ~2-5 POL for gas. Re-arm Auto-Trade.
4. **Observe ONE micro-trade.** Let exactly one `late_entry_v3` candidate route live. The audit trace is: `live_order_intent` → orders row `mode='live' status='submitted' polymarket_order_id=...` → positions row `mode='live'` → `notify_entry` web + Telegram alert → close path on TP/SL/strategy_exit → ledger credit + close audit + close notification. Verify on the Polymarket dashboard.
5. **Halt + rollback.** Kill switch (`/emergency`, DB `kill_switch_active=true`, or env `KILL_SWITCH=true`) halts new orders instantly; flip any guard back to `false` to route new trades to paper. Existing open positions remain unwindable.

Per the hard safety constraints in the issue, this runbook is operator-driven; nothing in CI / the repo flips any guard or moves any funds.

## 6. Files created / modified

- `projects/polymarket/crusaderbot/tests/test_clob_micro_live_preflight.py` (new — 17-test issue-#1817 matrix)
- `projects/polymarket/crusaderbot/reports/forge/clob-micro-live-open-order-path.md` (this report)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md` (repo-truth sync)

Nothing in `domain/execution/live.py`, `domain/risk/`, `domain/strategy/`, `integrations/clob/`, `wallet/`, `config.py`, or any migration was touched — the existing path is the deliverable.

## 7. Validation evidence

- New `test_clob_micro_live_preflight.py` -> 17 passed (each row in §4 above).
- Full suite: `pytest projects/polymarket/crusaderbot/tests/` -> 3677 passed, 15 skipped.
- `ruff check` + `python3 -m py_compile` clean on the new test.
- Branch verified exactly `WARP/clob-micro-live-open-order-path` (issue-declared).
- Secret / mojibake / BOM scans clean on touched files.

## 8. Safety invariant statement

No live order placed by CI / tests. No real funds moved. No live-guard flip (`USE_REAL_CLOB` / `EXECUTION_PATH_VALIDATED` / `ENABLE_LIVE_TRADING` / `CAPITAL_MODE_CONFIRMED` / `RISK_CONTROLS_VALIDATED` / `SECURITY_HARDENING_VALIDATED` untouched). Kelly stays 0.25 (never full); `LIVE_MIN_ORDER_SHARES=5`; `SLIPPAGE_GUARD_PCT=0.05`; per-user balance isolation; $5 live Auto-Trade start gate; kill switch all unchanged. No strategy / preset / risk constant / migration changed. The new test file is hermetic by construction: no imports of v2/adapter/sidecar clients; no `aiohttp`; every `execute()` invocation goes through the patched `_run` helper (pinned by the hermeticity test).

## 9. What is next

WARP🔹CMD first-pass; merge under WARP•R00T final gate on CI green (verification + preflight matrix + runbook; no capital path touched). After merge, the operator runbook in `reports/forge/go-live-readiness.md` (steps 0-7) is the path to a real funded micro-trade. The deferred lanes (native USDC/USDT enablement #1805, `late_entry_v3` edge calibration #1815) remain owner-gated and are explicitly out of scope here.

---

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: docs-aligned verification of the existing CLOB live open-order path + explicit single-table preflight matrix + narrow runbook anchor.
Not in Scope: any runtime / risk / strategy / config / live-guard / migration change; real fund movement; native USDC/USDT crediting; Bridge/pUSD; strategy calibration.
Suggested Next Step: WARP🔹CMD first-pass -> R00T final-gate merge on CI green; operator executes the runbook for a single funded micro-trade.
