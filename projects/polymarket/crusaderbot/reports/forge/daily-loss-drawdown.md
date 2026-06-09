# WARP•FORGE — User-configurable daily loss limit + max drawdown halt (#4)

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: user-overridable daily $-loss ceiling and max drawdown % halt, both bounded by hard system floors; surfaced + editable in the Risk Profile UI. Also includes bug fix: exit_price display for 0¢ (resolution_loss) positions was showing "—" due to Python falsy check on 0.0.
Not in Scope: SENTINEL audit (can be run if WARP🔹CMD requests); Home page enhancements (next lane); Kelly / position / per-trade fences (unchanged).
Suggested Next Step: Apply migration 054 to prod Supabase → WARP🔹CMD review + deploy → then Home page enhancements.

## 1. What was built

Two user-configurable risk override controls — both stricter-only, system floors are immovable:

**Daily Loss Limit override**
- `daily_loss_override` column already existed in `user_settings` (migration 001) — infra was already present.
- Backend now exposes it via the `/autotrade` GET response (echo) and `/autotrade/customize` POST (validate + persist).
- Validation: must be negative (e.g. -300), bounded to `[-2000, 0)`. Effective cap = most restrictive of system -$2000, profile default, and user override (`effective_daily_loss()` in constants.py — unchanged).
- UI: `DailyLossControl` — shows profile default + effective cap; user enters a positive dollar amount (negated internally); Reset button clears override.

**Max Drawdown % halt override**
- `max_drawdown_pct NUMERIC CHECK (0 < x <= 0.08)` added to `user_settings` via migration 054.
- Gate layer (`_max_drawdown_breached`) now accepts `user_drawdown_pct: float | None`: threshold = `min(8%, user_pct)` — user can only halt earlier, never later.
- `GateContext.max_drawdown_pct` added (default None = system 8% applies).
- Wired through `TradeSignal.max_drawdown_pct` → `engine._build_gate_context()` → `gate.evaluate()`.
- Signal scan query fetches `s.max_drawdown_pct` from `user_settings`.
- UI: `MaxDrawdownControl` — shows effective % (your override or 8%); Reset button clears.

**Exit price display bug fix**
- `router.py` GET `/positions` mapped `current_price` with `if r["current_price"]` (Python falsy check), causing `0.0` (resolution_loss positions) to become `None` → frontend showed "—" for Exit Price.
- Fixed to `if r["current_price"] is not None`. Same fix applied to `pnl_usdc`.

## 2. Current system architecture

`effective_daily_loss(profile, user_override)` → most restrictive of system/profile/user (in constants.py, unchanged).
`_max_drawdown_breached(user_id, user_drawdown_pct=None)` → threshold = `min(MAX_DRAWDOWN_HALT=0.08, user_pct)` if user provided.
Gate step 5 (daily loss) uses the existing `effective_daily_loss` path via `GateContext.daily_loss_override`.
Gate step 6 (drawdown) now takes `ctx.max_drawdown_pct` from the signal → `TradeSignal` → `GateContext`.
The autotrade GET endpoint fetches both fields from `user_settings` and echoes them for the UI form. The customize endpoint validates + persists via the existing `_add()` pattern.

## 3. Files created / modified

- projects/polymarket/crusaderbot/migrations/054_user_daily_drawdown_settings.sql (new — adds max_drawdown_pct col + CHECK)
- projects/polymarket/crusaderbot/domain/risk/gate.py (GateContext += max_drawdown_pct; _max_drawdown_breached += user_drawdown_pct param; evaluate() passes ctx.max_drawdown_pct)
- projects/polymarket/crusaderbot/services/trade_engine/engine.py (TradeSignal += max_drawdown_pct; _build_gate_context passes it)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py (query += s.max_drawdown_pct; _build_trade_signal wire)
- projects/polymarket/crusaderbot/webtrader/backend/schemas.py (AutoTradeState += daily_loss_override, max_drawdown_pct; CustomizeRequest += same)
- projects/polymarket/crusaderbot/webtrader/backend/router.py (autotrade GET: fetch+return both; customize POST: validate+persist; positions: if is not None bugfix)
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts (AutoTradeState + CustomizeParams += daily_loss_override, max_drawdown_pct)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx (DailyLossControl + MaxDrawdownControl components; wired in Risk Profile section)
- projects/polymarket/crusaderbot/tests/test_late_entry_v3.py (+2 tests: effective_daily_loss restrictiveness; drawdown threshold logic)
- projects/polymarket/crusaderbot/reports/forge/daily-loss-drawdown.md (this report)

## 4. What is working

- Full suite 1762 passed (+2 new) + ruff clean.
- System floors always apply: `min(8%, user_pct)` so user setting 10% still triggers at 8%; user -$50 daily loss (stricter than -$500 balanced) → gate halts at -$50.
- `effective_daily_loss()` unchanged — used by gate step 5; user override fed via `GateContext.daily_loss_override` (same wire path as before, now also echoed in `/autotrade` GET).
- Exit price "—" bug fixed: `0.0` (resolution_loss) now correctly shows `0.0¢` in the expanded trade detail.
- DailyLossControl shows effective cap dynamically (profile default or user override, whichever is stricter).
- MaxDrawdownControl shows effective % (always ≤ 8%).

## 5. Known issues

- Migration 054 must be applied to production Supabase before deploy (additive, idempotent, safe).
- Frontend tsc/vite not run locally (no node_modules) — CI is the gate.
- `daily_loss_override` infra existed since migration 001 but was not surfaced in UI before this PR. Any pre-existing DB value now visible and editable; no data migration needed.

## 6. What is next

- WARP🔹CMD: apply migration 054 → review → deploy.
- Home page enhancements: signal scanner liveness (time + daily count), open positions expanded by default in Home, recent activity slide (5 latest).
