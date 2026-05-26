# WARP•FORGE — User-configurable "Max $ per trade" (#3)

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: per-user max-per-trade ceiling with two opt-in modes (fixed $ /
% equity) bounded by hard system limits; surfaced + editable in the Risk Profile UI.
Not in Scope: daily-loss + max-drawdown controls (that is lane #4, next PR); Kelly /
position / drawdown fences (unchanged). Paper-only.
Suggested Next Step: WARP🔹CMD review + deploy; then lane #4 (daily $-loss + max
drawdown %). SENTINEL optional (additive, bounded, paper).

## 1. What was built

Owner-directed (default chosen by FORGE): a per-user max-$-per-trade control with
three modes —
- **auto** (DEFAULT): system $25 flat ceiling — existing behaviour, unchanged.
- **fixed**: `max_per_trade_usdc`, bounded in code to **[$1, $500]**.
- **pct**: `max_per_trade_pct` of equity, bounded to **[0.5%, 10%]**.

A user can RAISE above $25 (fixed/pct) for bigger accounts or LOWER it, but never beyond
the absolute system limits; the risk gate's fractional Kelly + 10%-of-equity position
fence still apply on top. Default stays 'auto' so existing users are unaffected until
they opt in.

## 2. Current system architecture

`resolve_per_trade_ceiling(equity, mode, usd, pct)` -> the $ ceiling; fed into
`suggested_trade_size(equity, cap%, ceiling_usdc=…)`. The strategy reads the user's
mode/values from `UserContext` (populated by signal_scan_job from user_settings). The
WebTrader `/autotrade` endpoint resolves the same ceiling so the UI's "Max per trade"
matches the engine, and echoes back the saved mode/values for the form. Saved via
`/autotrade/customize`. Migration 053 adds the columns + a CHECK on the mode.

## 3. Files created / modified

- migrations/053_user_max_per_trade.sql (APPLIED to prod — additive, idempotent: 3 cols
  + mode CHECK constraint)
- domain/strategy/strategies/late_entry_v3.py (new `resolve_per_trade_ceiling()`;
  `suggested_trade_size(..., ceiling_usdc=)`; hard limits $500 / 0.5–10%; exported)
- domain/strategy/types.py (UserContext += max_per_trade_mode/usdc/pct)
- services/signal_scan/signal_scan_job.py (query + _build_user_context wire the 3 cols)
- webtrader/backend/schemas.py (AutoTradeState: computed field renamed ->
  effective_max_per_trade_usdc, + mode/usdc/pct echo; CustomizeRequest += 3 fields)
- webtrader/backend/router.py (autotrade endpoint resolves mode-aware ceiling; customize
  endpoint validates + persists; import resolve_per_trade_ceiling)
- webtrader/frontend/src/lib/api.ts (AutoTradeState + CustomizeParams types)
- webtrader/frontend/src/pages/AutoTradePage.tsx (renamed display ref; new
  <MaxPerTradeControl> — mode buttons + bounded input + save)
- tests/test_late_entry_v3.py (+3 tests: resolve modes/clamps; fixed-cap; pct-cap)
- reports/forge/user-max-per-trade.md (this report)

## 4. What is working

- Full suite 1760 passed (+3 new) + ruff clean.
- Ceilings bounded in code regardless of DB values (a malicious/large DB value still
  clamps to $500 / 10%). Default 'auto' preserves current behaviour exactly.
- Single source of truth: engine and UI both use resolve_per_trade_ceiling +
  suggested_trade_size.

## 5. Known issues

- Raising the ceiling only yields bigger trades up to the natural size
  (equity x CAP% x 4%); to size larger the user also raises CAP% (risk profile). The
  ceiling is a cap, not a target — intended.
- Frontend tsc/vite not run locally (no node_modules) — CI is the gate.
- Only the late_entry_v3 (Close Sweep) sizing path consumes the per-trade ceiling today;
  other strategies size via their own logic + the gate fences.

## 6. What is next

- Lane #4: expose the existing daily_loss_override + add a user max-drawdown %
  (stricter of system 8% vs user) in the gate + Risk UI.
