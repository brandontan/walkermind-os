# WARP•FORGE — smart-strike-friendly-signal-status-polish

Branch: `work`
Issue: #1807
Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Role: WARP•FORGE
Date: 2026-06-13 05:50 Asia/Jakarta

Validation Target: Polish the WebTrader Smart Strike scanner status so already-surfaced no-trade telemetry renders as operator-friendly copy instead of raw snake_case reason codes.

Not in Scope: strategy logic, risk logic, order placement, signal generation, live guards, backend status contract changes, deposit/withdrawal paths, or any real fund movement.

---

## 1. What was built

The ScannerPanel already consumed `RuntimeStatus.smart_strike_no_trade_reason`, but it displayed most reasons as raw telemetry codes such as `orderbook_empty` or `step_14_below_min_order_shares`. This lane adds a small frontend-only formatter that preserves the existing telemetry contract while rendering concise user-facing status text:

- `skipped_orderbook_empty` -> `order book empty`
- `skipped_liquidity` -> `liquidity too thin`
- `step_14_below_min_order_shares` -> `below minimum order size`
- `late_entry_v3:measured_edge_missing` -> `late-entry filter blocked setup: measured edge unavailable`
- structural fallbacks like `no_candidates` -> `no qualifying setup yet`

Unknown reasons still degrade deterministically by trimming the noisy `skipped_` prefix and replacing underscores with spaces, so new backend reason codes remain visible instead of disappearing.

## 2. Files modified

- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/ScannerPanel.tsx` — added `formatNoTradeReason()` plus curated reason/token label maps; the active status line now renders `awaiting_signal · <friendly reason>` from the formatter.
- `projects/polymarket/crusaderbot/tests/test_smart_strike_no_trade_reason.py` — pinned that ScannerPanel uses the formatter and no longer does the previous inline `skipped_`-only replacement.
- `projects/polymarket/crusaderbot/reports/forge/smart-strike-friendly-signal-status-polish.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `projects/polymarket/crusaderbot/state/WORKTODO.md`, `projects/polymarket/crusaderbot/state/CHANGELOG.md` — repo-truth state updates for #1807.

## 3. Safety invariant statement

This is frontend presentation polish only. It does not alter `summarize_no_trade_reason()`, `/status`, `RuntimeStatus`, scan telemetry persistence, eligibility gates, risk checks, order intent, CLOB execution, balances, deposits, withdrawals, or any activation flag. No live-guard flag was flipped (`USE_REAL_CLOB`, `EXECUTION_PATH_VALIDATED`, `ENABLE_LIVE_TRADING`, `CAPITAL_MODE_CONFIRMED` untouched). No order was placed and no funds moved.

## 4. Validation

- `pytest projects/polymarket/crusaderbot/tests/test_smart_strike_no_trade_reason.py` -> 19 passed.
- `cd projects/polymarket/crusaderbot/webtrader/frontend && npm run build` -> `tsc && vite build` passed; Vite emitted only the existing mixed dynamic/static import chunk warning for `PortfolioPage.tsx`.
- Screenshot captured with a temporary Vite harness and real `ScannerPanel` props at `/tmp/smart-strike-friendly-status.png`; temporary harness files were removed before commit.

## 5. Suggested next step

WARP🔹CMD review only. This lane is MINOR UI/status-copy polish and WARP•SENTINEL is not allowed by AGENTS.md for MINOR lanes.
