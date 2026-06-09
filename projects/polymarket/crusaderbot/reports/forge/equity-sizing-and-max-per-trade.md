# WARP•FORGE — Equity-based sizing + "Max per trade" UI clarity (#1 + #2)

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: per-trade sizing base (free balance -> equity) + surfacing the real
max-per-trade in the WebTrader Risk Profile UI so CAP% isn't read as the per-trade size.
Not in Scope: risk fences (Kelly / max-position / daily-loss / drawdown — these are the
#3/#4 lane), Telegram UI, exit logic. Paper-only; ENABLE_LIVE_TRADING untouched.
Suggested Next Step: WARP🔹CMD review + deploy; then lane #3/#4 (user-set max $/trade +
max daily drawdown) as a separate SENTINEL-gated risk lane.

## 1. What was built

Owner concern: "CAP% by equity not balance; 60% shouldn't mean $600/trade on $1000."

- **#2 Equity-based sizing.** Per-trade size now sizes off **equity** (free balance +
  open-position cost), not idle cash. New `UserContext.equity_usdc` (defaults 0.0,
  falls back to available_balance for older callers/tests). signal_scan_job computes
  equity = balance + SUM(open size_usdc) per user.
- **#1 Max-per-trade clarity.** Confirmed CAP% is the deployable POOL, not the trade
  size — per-trade is `equity x CAP% x 4%`, hard-capped at $25 (so $1000 x 60% = $24,
  not $600). Extracted the formula into a shared `suggested_trade_size()` used by BOTH
  the strategy and the WebTrader `/autotrade` endpoint, which now returns
  `equity_usdc` + `max_per_trade_usdc`. The Risk Profile screen shows
  "Max per trade: $X · CAP N% of $E equity is the deployable pool, not one trade".

## 2. Current system architecture

late_entry_v3.scan -> `suggested_trade_size(equity, cap%)` -> RISK gate (unchanged:
fractional Kelly + max-position + daily-loss + drawdown) -> execute. The same helper
feeds GET /api/web/autotrade so the UI number matches what the engine will use (single
source of truth). Equity is computed identically in two places (cost-basis): the scan
user-query and the autotrade endpoint.

## 3. Files created / modified

- domain/strategy/types.py (UserContext += equity_usdc, validated >= 0)
- domain/strategy/strategies/late_entry_v3.py (new `suggested_trade_size()`; sizing base
  = equity_usdc or available_balance; exported)
- services/signal_scan/signal_scan_job.py (user query += open_cost_usdc subquery;
  _build_user_context computes equity = balance + open_cost)
- webtrader/backend/schemas.py (AutoTradeState += equity_usdc, max_per_trade_usdc)
- webtrader/backend/router.py (autotrade endpoint fetches equity; imports + calls
  suggested_trade_size; returns both fields)
- webtrader/frontend/src/lib/api.ts (AutoTradeState += equity_usdc, max_per_trade_usdc)
- webtrader/frontend/src/pages/AutoTradePage.tsx (Risk Profile: "Max per trade" banner)
- tests/test_late_entry_v3.py (+2 tests: suggested_trade_size floor/cap; sizes off equity)
- reports/forge/equity-sizing-and-max-per-trade.md (this report)

## 4. What is working

- Full suite 1755 passed + 2 new (1757) locally; ruff clean.
- Equity fallback keeps every existing UserContext caller/test correct.
- Sizing stays bounded: max_concurrent x $25 cap; equity-base never exceeds real free
  cash at execution (the ledger debit still gates affordability).

## 5. Known issues

- Equity here is cost-basis (balance + open size_usdc), not mark-to-market — chosen for
  simplicity and to avoid side-aware mark math in the hot path; differs from the
  Portfolio page equity (which adds unrealized PnL) by the small open unrealized amount.
- max-per-trade shown is for the ACTIVE CAP%; the inactive preset cards don't show a
  per-card figure (kept single-source via the backend value).

## 6. What is next

- Lane #3 + #4: user-configurable "Max $ per trade" (override the $25 ceiling, bounded by
  the system max) and "Max daily drawdown %" (currently a fixed 8% halt + per-profile $
  loss). These touch the safety fences -> MAJOR + SENTINEL.
