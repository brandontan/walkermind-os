# WARP•FORGE REPORT: capital-validation-p8e
Branch: WARP/capital-validation-p8e
Date: 2026-04-30 05:19 Asia/Jakarta

---

## Validation Metadata

- Branch: WARP/capital-validation-p8e
- Validation Tier: STANDARD
- Claim Level: NARROW INTEGRATION
- Validation Target: P8-E capital validation + claim review — dry-run, staged rollout assessment, docs audit, claim cleanup, CAPITAL_MODE_CONFIRMED decision
- Not in Scope: New features, new tests, runtime changes outside capital flag, real CLOB implementation, live market data, per-user portfolio binding
- Suggested Next Step: WARP🔹CMD review; CAPITAL_MODE_CONFIRMED NOT SET — see section 6 for gate criteria

---

## 1. What Was Built

### E1 — Dry-run capital mode guard validation

Four guard test scenarios executed against `CapitalModeConfig.from_env()`:

| Test | Scenario | Result |
|---|---|---|
| T1 | PAPER mode, all gates OFF | PASS — no exception, `is_capital_mode_allowed()=False` |
| T2 | LIVE mode, all gates OFF | PASS — `CapitalModeGuardError` raised, all 5 gates listed as missing |
| T3 | LIVE mode, all gates ON (dry-run only) | PASS — `validate()` succeeds, `is_capital_mode_allowed()=True` |
| T4 | LIVE mode, 3/5 gates ON | PASS — raises with `EXECUTION_PATH_VALIDATED`, `SECURITY_HARDENING_VALIDATED` listed missing |

No unintended live capital exposure possible in current deployment: all gates default to `False`; any attempt to activate LIVE without all 5 gates raises `CapitalModeGuardError` with CRITICAL log.

### E2 — Staged rollout assessment

Current state: **Stage 0 — Paper mode only.** Capital mode guard blocks all live execution.

Staged rollout criteria before any live capital deployment:

| Stage | Gate | Prerequisite | Current State |
|---|---|---|---|
| 0 | Baseline | Paper mode guard verified | ✅ DONE — P8-A/B/C/D merged |
| 1 | Execution ready | Real CLOB order submission path implemented + tested (P8-C-1) | ❌ NOT DONE |
| 1 | Market data | `PaperBetaWorker.price_updater` replaced with live data polling (P8-C-2) | ❌ NOT DONE |
| 1 | Settlement | `SettlementWorkflow.allow_real_settlement` path validated end-to-end (P8-C-3) | ❌ NOT DONE |
| 2 | Risk gates | `RISK_CONTROLS_VALIDATED=true` set (P8-B SENTINEL APPROVED) | ✅ READY |
| 2 | Security gates | `SECURITY_HARDENING_VALIDATED=true` set (P8-D SENTINEL APPROVED 97/100) | ✅ READY |
| 3 | Execution gate | `EXECUTION_PATH_VALIDATED=true` set (requires Stage 1 + P8-C APPROVED) | ❌ NOT READY |
| 4 | Capital confirm | `CAPITAL_MODE_CONFIRMED=true` set by WARP🔹CMD (requires all gates) | ❌ NOT SET |
| 4 | Live opt-in | `ENABLE_LIVE_TRADING=true` confirmed intentional | ❌ WARP🔹CMD decision |

**Initial capital exposure cap:** When Stage 3 is ready, initial live deployment must start with `CAPITAL_MAX_POSITION_FRACTION=0.02` (current default — 2% per position), `CAPITAL_DAILY_LOSS_LIMIT_USD=-500` (reduced from -$2,000 for initial live run), monitored for minimum 5 trading sessions before cap is lifted.

### E3 — Docs overclaim audit

All docs reviewed for live-trading-ready or production-capital-ready language.

| File | Finding |
|---|---|
| `docs/announcement_package_draft.md` | CLEAN — "Not production-capital ready" ✓ |
| `docs/operator_runbook.md` | CLEAN — "not live-trading ready and not production-capital ready" ✓ |
| `docs/post_release_readiness_summary.md` | CLEAN — "Not live-trading ready", "Not production-capital ready" ✓ |
| `docs/paper_only_boundary_statement.md` | CLEAN — explicit paper-only statement ✓ |
| `docs/launch_posture_summary.md` | CLEAN — excludes live-trading/capital readiness claims ✓ |
| `server/api/public_beta_routes.py` | CLEAN — `live_trading_ready: False` in all status routes ✓ |
| `client/telegram/presentation.py` | CLEAN — "Not live-trading ready", "Not production-capital ready" in all public boundaries ✓ |

No overclaim found. No changes required.

### E4 — Boundary registry status cleanup

Updated `server/config/boundary_registry.py` to reflect P8-C hardening:

| Surface | Before | After | Reason |
|---|---|---|---|
| `PaperBetaWorker.price_updater` | `NEEDS_HARDENING` | `BLOCKED` | P8-C: raises `LiveExecutionBlockedError` in live mode — surface actively blocks capital mode |
| `WalletCandidate.financial_fields_zero` | `NEEDS_HARDENING` | `BLOCKED` | P8-C: `MissingRealFinancialDataError` raised for zero-equity in live mode — surface actively blocks capital mode |

Registry final state: 1 `SAFE_AS_IS`, 9 `NEEDS_HARDENING`, 4 `BLOCKED`.

### E5 — Risk constants verification

All locked risk constants confirmed correct in `capital_mode_config.py`:

| Constant | Required | Actual |
|---|---|---|
| `KELLY_FRACTION` | `0.25` | `0.25` ✓ |
| `MAX_POSITION_FRACTION_CAP` | `<= 0.10` | `0.10` ✓ |
| `DAILY_LOSS_LIMIT` default | negative | `-2000.0` ✓ |
| `DRAWDOWN_LIMIT_CAP` | `<= 0.08` | `0.08` ✓ |
| `MIN_LIQUIDITY_USD_FLOOR` | `>= 10000` | `10000.0` ✓ |

---

## 2. Current System Architecture

```
CapitalModeConfig (server/config/capital_mode_config.py)
  Gates (all default OFF):
    Gate 1: ENABLE_LIVE_TRADING
    Gate 2: CAPITAL_MODE_CONFIRMED      ← P8-E sign-off gate (NOT SET)
    Gate 3: RISK_CONTROLS_VALIDATED     ← P8-B SENTINEL APPROVED — ready to set
    Gate 4: EXECUTION_PATH_VALIDATED    ← P8-C CONDITIONAL — CANNOT SET (real CLOB not built)
    Gate 5: SECURITY_HARDENING_VALIDATED ← P8-D SENTINEL APPROVED — ready to set

LiveExecutionGuard (server/core/live_execution_control.py)
  5-check blocking order:
    1. kill_switch
    2. mode != "live"
    3. ENABLE_LIVE_TRADING env var
    4. CapitalModeConfig.validate() — all 5 gates
    5. WalletFinancialProvider non-zero check

BoundaryRegistry (server/config/boundary_registry.py)
  14 surfaces tracked: 1 SAFE_AS_IS / 9 NEEDS_HARDENING / 4 BLOCKED
  CRITICAL surfaces (5): PaperExecutionEngine, LiveExecutionGuard, PaperRiskGate,
                         SettlementWorkflow, WalletCandidate.financial_fields_zero
```

---

## 3. Files Created / Modified (full repo-root paths)

**Modified:**
```
projects/polymarket/polyquantbot/server/config/boundary_registry.py
```

**Created:**
```
projects/polymarket/polyquantbot/reports/forge/capital-validation-p8e.md
```

---

## 4. What Is Working

- All 4 dry-run guard scenarios pass
- 70/70 P8 tests pass (CR-01..CR-28 covering P8-A/B/C/D)
- `CapitalModeGuardError` fires deterministically with CRITICAL log when LIVE mode attempted with missing gates
- Risk constants verified at correct locked values
- Docs audit: zero overclaim across all reviewed files
- Boundary registry updated — BLOCKED status accurately reflects P8-C hardened surfaces
- `CAPITAL_MODE_CONFIRMED` guard contract confirmed: any live execution attempt without all 5 gates raises immediately

---

## 5. Known Issues

- Real CLOB order submission path not implemented — `EXECUTION_PATH_VALIDATED` cannot be set; live capital deployment is blocked until this is built (P8-C-1, P8-C-2 not met).
- Daily loss limit resets to 0.0 on restart (same-day pre-restart losses not carried over) — conservative by design; DB-backed day-scope requires P9.
- Staged rollout initial-exposure cap (Stage 4) is a recommendation only — WARP🔹CMD must confirm deployment parameters before live.

---

## 6. What Is Next

### CAPITAL_MODE_CONFIRMED decision

**NOT SET.** Reason: `EXECUTION_PATH_VALIDATED=true` prerequisite is not met.

P8-C SENTINEL was CONDITIONAL (78/100). FLAG-1 was resolved by P8-D (SENTINEL APPROVED 97/100). However, P8-C gate criteria P8-C-1 ("live execution path verified — real CLOB order submission path exists and is tested") has NOT been satisfied. `EXECUTION_PATH_VALIDATED=true` may only be set after P8-C is re-validated as APPROVED. Until then, setting `CAPITAL_MODE_CONFIRMED=true` would be inconsistent with the gate contract — and any LIVE attempt would still fail at gate 4 (`EXECUTION_PATH_VALIDATED=False`).

Gates that ARE ready to set (WARP🔹CMD decision):
- `RISK_CONTROLS_VALIDATED=true` — P8-B SENTINEL APPROVED
- `SECURITY_HARDENING_VALIDATED=true` — P8-D SENTINEL APPROVED 97/100

Gates that CANNOT be set yet:
- `EXECUTION_PATH_VALIDATED=true` — requires real CLOB implementation + P8-C SENTINEL re-run → APPROVED
- `CAPITAL_MODE_CONFIRMED=true` — requires all other gates to be settable first
- `ENABLE_LIVE_TRADING=true` — WARP🔹CMD deployment decision (same prerequisite)

### Suggested Next Step

WARP🔹CMD review of P8-E findings:
1. Decide whether to set `RISK_CONTROLS_VALIDATED=true` and `SECURITY_HARDENING_VALIDATED=true` in deployment env now.
2. Open a new lane for real CLOB execution path implementation (P8-C-1 / P8-C-2) — required before `EXECUTION_PATH_VALIDATED` and `CAPITAL_MODE_CONFIRMED` can be set.
3. After CLOB lane closes: P8-C SENTINEL re-run → if APPROVED, set `EXECUTION_PATH_VALIDATED=true` → then `CAPITAL_MODE_CONFIRMED=true`.
