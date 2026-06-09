# WARP•R00T FORGE REPORT — candle-scan-telemetry

Branch: WARP/ROOT/candle-scan-telemetry
Date: 2026-05-29 03:31 Asia/Jakarta
Role: WARP•R00T

Validation Tier   : MINOR
Claim Level       : NARROW INTEGRATION
Validation Target : scan_runs telemetry accuracy for the close_sweep_fast_scan path
Not in Scope      : runtime trade logic, risk gate, candle strategy behavior, live execution

## 1. What was built

Two targeted fixes to `signal_scan_job.py` making `scan_runs` telemetry honest:

**Fix A — `markets_seen = 0` for candle fast-scan runs (misleading)**
`run_close_sweep_fast` created positions while writing `markets_seen=0` to `scan_runs`
because the candle scanner fetches markets from its own cache (`get_crypto_window_markets`)
outside the main market-scan counter. Result in prod: rows showing
`markets_seen=0, positions_created=3` — confusing when debugging.

Now: `_candle_markets_seen` accumulates `max(len(crypto_window_markets))` across users
in the tick; `tel.markets_seen` is set before the scan_runs row is persisted.
Post-fix: rows will show `markets_seen=5` (BTC/ETH/SOL/XRP/DOGE) alongside positions.

**Fix B — `mode='LIVE'` label in main `run_once` scan inconsistent with fast scan**
`run_once` set `mode = "LIVE"` if `ENABLE_LIVE_TRADING` alone was True (single-flag check).
`run_close_sweep_fast` already used the 3-guard check (`ENABLE_LIVE_TRADING and
EXECUTION_PATH_VALIDATED and CAPITAL_MODE_CONFIRMED`). Inconsistency: in a Fly env
where only `ENABLE_LIVE_TRADING=True`, the main scan showed `mode='LIVE'` while
the fast scan showed `mode='PAPER'` — or vice versa. Now both use the same 3-guard check.

Note: this does NOT change trading behavior. Actual live trading requires 5 guards +
`USE_REAL_CLOB + role='admin' + trading_mode='live'` — unaffected.

## 2. Current system architecture

Telemetry flow unchanged. `scan_runs` table stores one row per scan tick that creates
positions (candle fast-scan) or per every main-scan tick. The `markets_seen` and `mode`
columns are now accurate for both scan types.

## 3. Files created / modified

Modified: projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
  - `run_close_sweep_fast`: added `_candle_markets_seen` accumulator + `tel.markets_seen = _candle_markets_seen`
  - `run_once`: `_live_trading` now checks 3 guards (was ENABLE_LIVE_TRADING only)

Modified: projects/polymarket/crusaderbot/tests/test_signal_scan_job.py
  - Added `test_run_close_sweep_fast_telemetry_markets_seen_reflects_candle_universe`
  - Added `test_run_once_mode_label_uses_three_guard_check`

## 4. What is working

- py_compile clean
- 2/2 new tests pass
- No runtime behavior change — monitoring-only fix

## 5. Known issues

None introduced.

## 6. What is next

- CLOB order tick-size / neg_risk fix: `live.py:222,397` + `lifecycle.py:678` call
  `post_order` without `tick_size`/`neg_risk`; `get_tick_size`/`get_neg_risk` exist but
  have zero callers → CLOB rejects non-tick-aligned prices for live trades.
  This is the top pre-LIVE lane (LIVE-gated, needs staging validation).
- Consecutive empty candle-universe operator Telegram alert (follow-up from incident).
