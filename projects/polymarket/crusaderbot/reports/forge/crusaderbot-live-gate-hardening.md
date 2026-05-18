# WARP•FORGE REPORT — crusaderbot-live-gate-hardening

**Branch:** WARP/CRUSADERBOT-FAST-LIVE-GATE-HARDENING
**Date:** 2026-05-18 Asia/Jakarta
**Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** Fast Track D Live Gate Hardening — guard bypass detection, slippage fence (SLIPPAGE_GUARD_PCT), capital sanity checks (balance>0), kill switch path convergence (3 paths), dry-run endpoint.
**Not in Scope:** Enabling live trading, setting any guard to true, UI changes, new trading strategies.

> **NOTE:** This report supersedes the 2026-05-11 draft. Previous sections (1a–1e) remain below for historical context. New additions from this PR are documented in the NEW ADDITIONS section above each original section.

---

## NEW ADDITIONS (WARP/CRUSADERBOT-FAST-LIVE-GATE-HARDENING, 2026-05-18)

### Part A — Execution Path Guard Bypass Detection

- `domain/execution/live.py`: Added guard bypass detection at execution entry. CRITICAL log emitted as `GUARD_BYPASS_ATTEMPT` when `live.execute()` is called with any of the four activation guards unset. Defense-in-depth before `assert_live_guards()`.
- `domain/execution/router.py`: Guard bypass log level changed `WARNING` → `CRITICAL` for live→paper fallback.

### Part B — Shadow/Live Parity (dry_run_execute)

- `services/trade_engine/engine.py`: `ExecutionDryRun` dataclass + `TradeEngine.dry_run_execute()` added. Full pipeline (signal → risk → sizing) with no submission, no DB order writes.
- `api/admin.py`: `POST /admin/dry-run` endpoint (operator-only). Accepts signal params, returns `ExecutionDryRun` dict.

### Part C — SLIPPAGE_GUARD_PCT

- `domain/risk/constants.py`: `SLIPPAGE_GUARD_PCT = 0.05` added (line 26).
- `domain/execution/live.py`: Pre-submission fence: if `abs(limit_price - signal_price) / signal_price > SLIPPAGE_GUARD_PCT`, raises `LivePreSubmitError` logged at CRITICAL as `SLIPPAGE_REJECTED`.

### Part D — Capital Sanity balance>0

- `domain/risk/gate.py` — `validate_risk_caps()`: Cap 0 added: `balance > 0`. Rejects with `balance_zero_or_negative` before all other caps.

### Part E — Kill Switch Path Tests

- `tests/test_kill_switch_paths.py`: 3 unit tests added — `test_kill_switch_telegram`, `test_kill_switch_db`, `test_kill_switch_env`. All 3 pass.

### Part F — Readiness Report

- `state/LIVE_READINESS.md`: Generated with full status of all 6 hardening planes.

---

## Validation Checks (this PR)

```
✅ python3 -m py_compile on all 6 modified .py files — all clean
✅ python3 -m compileall projects/polymarket/crusaderbot — no errors
✅ pytest tests/test_kill_switch_paths.py — 3/3 pass
✅ grep ENABLE_LIVE_TRADING domain/execution/ — guard present on every live path
✅ SLIPPAGE_GUARD_PCT exists in domain/risk/constants.py
✅ No guard set to true anywhere in this PR
✅ state/LIVE_READINESS.md exists and complete
```

---

## Files Modified/Created (this PR)

Created:
- `projects/polymarket/crusaderbot/tests/test_kill_switch_paths.py`
- `projects/polymarket/crusaderbot/state/LIVE_READINESS.md`

Modified:
- `projects/polymarket/crusaderbot/domain/risk/constants.py`
- `projects/polymarket/crusaderbot/domain/execution/live.py`
- `projects/polymarket/crusaderbot/domain/execution/router.py`
- `projects/polymarket/crusaderbot/domain/risk/gate.py`
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py`
- `projects/polymarket/crusaderbot/api/admin.py`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`

---

## ORIGINAL REPORT (2026-05-11) — Foundation Work

**Branch:** WARP/crusaderbot-live-gate-hardening
**Date:** 2026-05-11 20:30 Asia/Jakarta
**Tier:** MAJOR
**Claim Level:** SAFETY HARDENING
**Validation Target:** Prove live execution path readiness without enabling live trading.
**Not in Scope:** Actual live activation, real-money execution, UI premium work, referral/admin systems.

---

## 1. What Was Built

Four hardening planes added to the existing 13-step risk gate pipeline:

**1a. Slippage / Market-Impact Gate (step 14)**

A new gate step appended to `domain/risk/gate.py`. Calls `check_market_impact(final_size, market_liquidity)` and rejects when `size_usdc / market_liquidity > MAX_MARKET_IMPACT_PCT (5%)`. Uses the Kelly-adjusted final size (post step 13) so the slippage guard sees the realistic committed capital, not the raw proposed size. Zero DB reads — pure function.

Two slippage constants added to `domain/risk/constants.py`:
- `MAX_MARKET_IMPACT_PCT = 0.05` (5% of visible depth)
- `MAX_SLIPPAGE_PCT = 0.03` (3% price deviation — for live pre-submit use)

**1b. Risk Assertion Audit Layer**

New module `domain/risk/hardening.py` with:
- `audit_risk_constants() → RiskAuditReport` — validates every hard-wired constant and every per-profile entry against its valid range. Returns typed report with all violations; never raises. Safe to call from ops endpoints.
- `assert_risk_constants()` — boot-time gate; raises `AssertionError` on any violation. Callers who need fatal-on-bad-config use this; the readiness validator uses `audit_risk_constants()`.

**1c. Shadow / Live Parity Validation Hooks**

New module `domain/execution/parity.py` with `validate_gate_parity(...)`. Runs the risk gate twice — once in paper mode (current posture) and once with all activation guards forced to True (simulated live). Compares the approved/rejected verdict and reports mismatch. No DB writes; patches `_log` and `_record_idempotency` for dry-run isolation.

**1d. Readiness Validator Service**

New service `services/validation/readiness_validator.py` with `ReadinessValidator` class running six checks:

| Check | What it validates |
|---|---|
| CHECK_RISK_CONSTANTS | All constants in safe range (via hardening.py) |
| CHECK_GUARD_STATE | All four activation guards are OFF (paper-safe posture) |
| CHECK_KILL_SWITCH | Cache invalidation + DB read path responsive |
| CHECK_EXECUTION_PATH | Full paper/live chain importable, key callables present |
| CHECK_CAPITAL_ALLOC | Kelly/size math consistent across profiles for ref $1,000 balance |
| CHECK_SLIPPAGE | Slippage module importable, thresholds in range, functional smoke test |

Returns `ReadinessReport` with per-check verdicts (PASS / FAIL / SKIP) and an overall verdict.

**1e. RISK_CONTROLS_VALIDATED config flag**

Added `RISK_CONTROLS_VALIDATED: bool = False` to `config.py` `Settings`. Defaults False. Must never be set to True without explicit WARP🔹CMD decision backed by a SENTINEL report.

---

## 2. Current System Architecture

```
Signal → TradeEngine → GateContext
                        ↓
                   13-step risk gate (domain.risk.gate.evaluate)
                        Step 1  — kill switch
                        Step 2  — user pause / auto-trade off
                        Step 3  — tier check
                        Step 4  — strategy availability
                        Step 5  — daily loss limit
                        Step 6  — max drawdown
                        Step 7  — max concurrent trades
                        Step 8  — correlated exposure cap
                        Step 9  — signal staleness
                        Step 10 — idempotency / dedup
                        Step 11 — liquidity floor
                        Step 12 — edge floor
                        Step 13 — market status + Kelly size cap + mode selection
                        Step 14 — slippage / market-impact cap  ← NEW
                        ↓
                   router.execute (paper or live fallback)
                        ↓ paper
                   paper.execute → DB + ledger

Hardening Layer (side channel, no production data path):
   ReadinessValidator.run()
     → CHECK_RISK_CONSTANTS   (hardening.audit_risk_constants)
     → CHECK_GUARD_STATE      (config.get_settings)
     → CHECK_KILL_SWITCH      (kill_switch.is_active — read only)
     → CHECK_EXECUTION_PATH   (importlib — no execution)
     → CHECK_CAPITAL_ALLOC    (pure math)
     → CHECK_SLIPPAGE         (slippage module smoke test)

Parity Hook (read-only dry run):
   parity.validate_gate_parity(...)
     → gate.evaluate (paper mode, no log/idempotency writes)
     → gate.evaluate (simulated live, no log/idempotency writes)
     → ParityReport (verdict_match boolean)
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/domain/risk/hardening.py`
- `projects/polymarket/crusaderbot/domain/execution/slippage.py`
- `projects/polymarket/crusaderbot/domain/execution/parity.py`
- `projects/polymarket/crusaderbot/services/validation/__init__.py`
- `projects/polymarket/crusaderbot/services/validation/readiness_validator.py`
- `projects/polymarket/crusaderbot/tests/test_live_gate_hardening.py`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-live-gate-hardening.md`

**Modified:**
- `projects/polymarket/crusaderbot/domain/risk/constants.py` — added `MAX_MARKET_IMPACT_PCT`, `MAX_SLIPPAGE_PCT`
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — added slippage step 14, imported `check_market_impact`
- `projects/polymarket/crusaderbot/config.py` — added `RISK_CONTROLS_VALIDATED: bool = False`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/WORKTODO.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What Is Working

- 35 hermetic tests green in `test_live_gate_hardening.py`.
- `audit_risk_constants()` correctly validates all 14 constants and 3 × 7 profile entries; returns typed violations list.
- `assert_risk_constants()` raises `AssertionError` on any violation; passes cleanly against current constants.
- `check_market_impact()` rejects orders with >5% market impact; accepts ≤5%; handles zero-liquidity edge case.
- `check_price_deviation()` rejects >3% deviation from reference price; accepts within range.
- Gate step 14 wired correctly: high-impact order (700/10_000 = 7%) rejected at step 14; acceptable order (100/10_000 = 1%) passes.
- `ReadinessValidator.run()` returns PASS for all 6 checks in paper-safe posture (all guards False).
- `CHECK_GUARD_STATE` fails correctly when `ENABLE_LIVE_TRADING=True` is detected.
- `CHECK_KILL_SWITCH` returns SKIP gracefully when DB pool is unavailable; PASS when kill switch is readable.
- `RISK_CONTROLS_VALIDATED` field present in `Settings`, defaults False, visible in `model_fields`.
- No activation guards touched. PAPER ONLY posture maintained throughout.

---

## 5. Known Issues

- `check_price_deviation()` is not yet wired into the gate or the live execution path. It is callable and tested but is only used by the readiness validator's smoke test. Wiring it into live pre-submit validation is a SENTINEL-gated next step (requires live execution path to be active).
- `parity.validate_gate_parity()` patches `gate.get_settings` to override guard values. This works correctly but couples the parity module to the gate's internal import path (`projects.polymarket.crusaderbot.domain.risk.gate.get_settings`). If the gate module path changes, the patch target must be updated.
- ENABLE_LIVE_TRADING code default in config.py remains True (existing deferred issue). The `CHECK_GUARD_STATE` check in the readiness validator will report FAIL if the fly.toml override is absent, which is the correct behaviour — it surfaces the mis-configuration rather than hiding it.

---

## 6. What Is Next

WARP•SENTINEL validation required before merge. Focus areas for SENTINEL:

- Verify step 14 rejects correctly under the full production dep chain (telegram, asyncpg, cryptography all present in CI).
- Verify `ReadinessValidator.run()` produces correct FAIL for each guard individually.
- Verify `audit_risk_constants()` catches profile violations (e.g., aggressive kelly > KELLY_FRACTION).
- Verify parity check divergence reporting when paper vs simulated-live gate verdicts differ.
- Confirm RISK_CONTROLS_VALIDATED default and that no code path flips it to True without SENTINEL approval.

---

**Validation Tier:** MAJOR
**Claim Level:** SAFETY HARDENING
**Validation Target:** Execution path readiness checks, risk assertion layer, slippage guardrail, kill switch verification — PAPER ONLY, no activation guards enabled.
**Not in Scope:** Live trading activation, real-money execution, UI, referral, admin.
**Suggested Next Step:** WARP•SENTINEL validate then WARP🔹CMD merge decision. After merge: Track E (Daily P&L Report, STANDARD).
