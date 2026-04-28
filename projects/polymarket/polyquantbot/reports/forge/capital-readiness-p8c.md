# WARP•FORGE REPORT: capital-readiness-p8c
Branch: WARP/capital-readiness-p8c-2a76
Date: 2026-04-29 00:54 Asia/Jakarta

---

## Validation Metadata

- Branch: WARP/capital-readiness-p8c-2a76
- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: live execution readiness path -- LiveExecutionGuard runtime wiring, CapitalRiskGate injection into PaperBetaWorker, WalletFinancialProvider real-data requirement, price_updater hardening, rollback/disable path, settlement_policy_from_capital_config gate wiring (CR-23..CR-35)
- Not in Scope: enabling production capital, setting CAPITAL_MODE_CONFIRMED or EXECUTION_PATH_VALIDATED to true, real CLOB order submission implementation, real market data feed integration, per-user capital isolation (P8-D), final public launch assets
- Suggested Next Step: WARP•SENTINEL MAJOR validation required before merge

---

## 1. What Was Built

### LiveExecutionGuard (`server/core/live_execution_control.py`)
Single pre-execution safety entry point that must pass before any live-mode execution path runs.

Checks in order:
1. `STATE.kill_switch` -- immediate block, no gate check needed
2. `STATE.mode == "live"` -- block if paper mode
3. `ENABLE_LIVE_TRADING` env var -- must be `"true"` (belt-and-suspenders, independent of config)
4. `CapitalModeConfig.validate()` -- all 5 gates must pass for LIVE mode
5. `WalletFinancialProvider` non-zero check -- provider must return real (non-stub) data

All failures raise `LiveExecutionBlockedError` with a machine-readable `reason` field and structured WARNING log.

### `disable_live_execution()` + `RollbackState` (`server/core/live_execution_control.py`)
Deterministic rollback/disable path:
- Sets `STATE.kill_switch = True`
- Sets `STATE.last_risk_reason = "rollback:{reason}"`
- Returns a `RollbackState` dataclass capturing reason, detail, disabled_at timestamp, prior kill_switch value
- Logs at WARNING level with all fields structured

### `PaperBetaWorker` hardening (`server/workers/paper_beta_worker.py`)
- Accepts `Union[PaperRiskGate, CapitalRiskGate]` via `AnyRiskGate` type alias
- Accepts optional `LiveExecutionGuard` via constructor injection
- When `STATE.mode != "paper"`:
  - If `live_guard` is injected: calls `guard.check(STATE)` before any execution; on failure triggers `disable_live_execution()` and skips the signal
  - If no `live_guard`: logs error, calls `disable_live_execution()`, skips signal (fail-closed)
- `price_updater()`: raises `LiveExecutionBlockedError` when `STATE.mode == "live"` and triggers `disable_live_execution()` -- the no-op stub is explicitly unsafe for live capital
- Paper path (`run_worker_loop`) unchanged -- `live_guard=None`, `PaperRiskGate()` as default

### `PortfolioFinancialProvider` (`server/risk/portfolio_financial_provider.py`)
Real implementation of `WalletFinancialProvider` backed by `PublicBetaState`:
- `get_balance_usd()` returns `STATE.wallet_equity`
- `get_exposure_pct()` returns `STATE.exposure`
- `get_drawdown_pct()` returns `STATE.drawdown`
- In live mode: raises `MissingRealFinancialDataError` if `wallet_equity` is zero (stub/uninitialized)
- In paper mode: zero equity is valid (fresh account)

### `settlement_policy_from_capital_config()` (`server/settlement/settlement_workflow.py`)
Factory that derives `SettlementWorkflowPolicy` from `CapitalModeConfig`:
- `allow_real_settlement = True` only when `is_capital_mode_allowed()` returns True (all 5 gates on, mode=LIVE)
- Prevents settlement from being enabled independently of the capital gate system
- Logs derived policy for operator visibility

### `BoundaryRegistry` updates (`server/config/boundary_registry.py`)
- `PaperExecutionEngine`: status updated to `NEEDS_HARDENING` (LiveExecutionGuard blocks at worker level)
- `PaperBetaWorker.price_updater`: status updated to `NEEDS_HARDENING` (raises in live mode, P8-C hardened)
- `LiveExecutionGuard`: new entry, `P8-C`, `NEEDS_HARDENING` (SENTINEL must validate full guard contract)
- `PaperRiskGate`: updated assumption to reflect P8-C duck-typed injection model
- `WalletCandidate.financial_fields_zero`: updated to reflect `PortfolioFinancialProvider` + `MissingRealFinancialDataError` guard

---

## 2. Current System Architecture

```
[Execution request -- paper mode]
        |
        v
PaperBetaWorker.run_once()
  STATE.mode == "paper" -- skip live guard
        |
        v
PaperRiskGate.evaluate(signal, STATE)
        |
        v
PaperExecutionEngine.execute(signal, STATE)  [paper fill -- no CLOB]
        |
        v
PaperBetaWorker.price_updater()  -- no-op (paper mode safe)

[Execution request -- live mode attempt]
        |
        v
PaperBetaWorker.run_once()
  STATE.mode != "paper" -- check live_guard
        |
        v
LiveExecutionGuard.check(STATE, provider)
  1. kill_switch check
  2. mode == "live" check
  3. ENABLE_LIVE_TRADING env var
  4. CapitalModeConfig.validate() -- all 5 gates
  5. provider non-zero check
  FAIL -> LiveExecutionBlockedError + disable_live_execution() -> STATE.kill_switch = True
        |
        v (only if all checks pass)
AnyRiskGate.evaluate(signal, STATE)  [CapitalRiskGate in live path]
        |
        v
[execution engine -- NOT YET IMPLEMENTED for LIVE]

[price_updater in live mode]
        |
        v
LiveExecutionBlockedError + disable_live_execution()
  reason: price_updater_stub_live_mode_blocked

[Settlement gating -- P8-C wired]
        |
        v
settlement_policy_from_capital_config(CapitalModeConfig)
  allow_real_settlement = is_capital_mode_allowed()
  [False unless all 5 gates on + mode=LIVE]
        |
        v
SettlementWorkflowEngine.execute()
  allow_real_settlement=False -> SETTLEMENT_STATUS_BLOCKED (safe)
```

---

## 3. Files Created / Modified (full repo-root paths)

**Created:**
```
projects/polymarket/polyquantbot/server/core/live_execution_control.py
projects/polymarket/polyquantbot/server/risk/portfolio_financial_provider.py
projects/polymarket/polyquantbot/tests/test_capital_readiness_p8c.py
projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8c.md
```

**Modified:**
```
projects/polymarket/polyquantbot/server/workers/paper_beta_worker.py
projects/polymarket/polyquantbot/server/settlement/settlement_workflow.py
projects/polymarket/polyquantbot/server/config/boundary_registry.py
projects/polymarket/polyquantbot/state/PROJECT_STATE.md
projects/polymarket/polyquantbot/state/WORKTODO.md
projects/polymarket/polyquantbot/state/CHANGELOG.md
```

---

## 4. What Is Working

- All 23 P8-C tests pass: CR-23..CR-35 (23 test cases including parametrized variants)
- All 35 P8-A+B regression tests pass: CR-01..CR-22 (35/35, no regressions)
- Total: 58/58 passing

**LiveExecutionGuard verified:**
- Blocks on kill_switch (CR-23)
- Blocks on non-live mode (CR-24, 4 parametrized variants)
- Blocks when ENABLE_LIVE_TRADING not set (CR-25)
- Blocks when capital gates are off (CR-26)
- Blocks when no provider injected (CR-27)
- Blocks when provider returns all-zero fields (CR-28)
- Passes when all gates on + non-zero provider (CR-29)

**Rollback/disable path verified:**
- `disable_live_execution()` sets kill_switch=True, logs reason, returns RollbackState (CR-30)
- Idempotent when kill_switch already set (CR-30b)

**price_updater hardening verified:**
- Raises `LiveExecutionBlockedError` in live mode and sets kill_switch via rollback (CR-31)

**PaperBetaWorker live guard blocking verified:**
- run_once() with no live_guard injected and mode=live triggers rollback (CR-32)

**PortfolioFinancialProvider verified:**
- Raises `MissingRealFinancialDataError` in live mode with zero equity (CR-33, CR-33b)
- Returns correct values in paper mode; zero equity is valid in paper (CR-34, CR-34b)

**Settlement policy wiring verified:**
- `allow_real_settlement=True` only when all 5 gates on (CR-35)
- Blocked when gates off (CR-35b)
- Blocked when one gate missing (CR-35c)
- `settlement_enabled=False` orthogonal to gate state (CR-35d)

**Paper-mode regression verified:**
- All P8-A/P8-B tests pass unmodified (CR-regression)
- `PaperBetaWorker` paper path unchanged: `live_guard=None`, `PaperRiskGate()` used in `run_worker_loop`

---

## 5. Known Issues

- `PaperExecutionEngine` is still paper-only -- no real CLOB order submission path exists. LiveExecutionGuard blocks live execution attempts at worker level (before engine is reached), but a real live execution engine is not built. `EXECUTION_PATH_VALIDATED` gate must NOT be set until a real CLOB path is validated.
- `PortfolioFinancialProvider` is backed by `PublicBetaState` (single-wallet, in-memory) -- a real market-data-backed provider for live mode requires market data feed integration (deferred).
- `price_updater()` raises in live mode but has no real implementation -- unrealized PnL will not update in live mode until a market data integration replaces this stub.
- `STATE.realized_pnl` is lifetime cumulative (not day-scoped) -- `daily_loss_limit` gate in `CapitalRiskGate` will permanently trip once cumulative losses exceed -$2000. Pre-existing bug from P8-B; deferred. SENTINEL must flag.
- `WalletFinancialProvider` all-zero check uses all-three-fields threshold -- a provider that returns non-zero exposure but zero balance would pass the guard. SENTINEL should verify this edge case is acceptable.
- `LiveExecutionGuard` is not wired into `run_worker_loop()` (paper-loop entry point) -- intentional. Paper path does not need the guard. Live path must construct a separate worker with guard injected.

---

## 6. What Is Next

- WARP•SENTINEL MAJOR validation required before merge
- P8-D: Security + observability hardening (§53) -- per-user capital isolation, admin audit log, production alerting, wire `CapitalRiskGate.status()` to Telegram; clears `SECURITY_HARDENING_VALIDATED` gate
- P8-E: Capital validation + claim review (§54) -- dry-run, staged rollout, docs sign-off; sets `CAPITAL_MODE_CONFIRMED=true`
- Pre-production: implement real CLOB execution engine and real market data provider before setting `EXECUTION_PATH_VALIDATED=true`
- Pre-production: fix `daily_loss_limit` to use day-scoped PnL (add `daily_realized_pnl` to `PublicBetaState` with daily reset logic)

---

## Metadata

- **Validation Tier:** MAJOR
- **Claim Level:** NARROW INTEGRATION (live execution guard + rollback path wired; no real CLOB, no real market data feed)
- **Validation Target:** live execution readiness path -- LiveExecutionGuard, CapitalRiskGate injection, WalletFinancialProvider real-data requirement, price_updater hardening, rollback/disable path, settlement policy gate wiring (CR-23..CR-35)
- **Not in Scope:** real CLOB execution, real market data feed, EXECUTION_PATH_VALIDATED gate set to true, CAPITAL_MODE_CONFIRMED, per-user isolation, final launch assets
- **Suggested Next Step:** WARP•SENTINEL MAJOR validation; P8-D after merge
