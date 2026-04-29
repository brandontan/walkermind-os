# WARP•SENTINEL VALIDATION REPORT: capital-readiness-p8c
Branch: WARP/capital-readiness-p8c-2a76
Date: 2026-04-29 08:30 Asia/Jakarta
Validated Head: c12805f3ca

---

## Validation Metadata

- Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Forge Report: projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8c.md
- Sentinel Report: projects/polymarket/polyquantbot/reports/sentinel/capital-readiness-p8c.md
- Environment: dev / asyncio / paper mode default — no real CLOB, no live capital
- Not in Scope: real CLOB path, market data feed, EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED, P8-D, P8-E

---

## PHASE 0 — Pre-Test

[1] Forge report at correct path + all 6 sections
    Path: projects/polymarket/polyquantbot/reports/forge/capital-readiness-p8c.md — EXISTS
    Sections: What Was Built / Architecture / Files / What Is Working / Known Issues / What Is Next — ALL PRESENT
    → PASS

[2] PROJECT_STATE.md updated
    Last Updated: 2026-04-29 01:30 — full timestamp present
    Status references P8-C, test count 25/25, 60/60 total
    All 5 ASCII bracket labels present
    → PASS

[3] No phase*/ folders + domain structure correct
    No phase*/ folders found in repo
    Code in locked domain: server/core/, server/workers/, server/risk/, server/settlement/, tests/
    → PASS

[4] Hard delete policy followed
    No shims, no re-export files, no compatibility layers introduced
    → PASS

[5] Implementation evidence for critical layers
    LiveExecutionGuard, disable_live_execution, PaperBetaWorker, PortfolioFinancialProvider all present
    → PASS

PHASE 0: ALL PASS — proceeding to validation.

---

## TEST PLAN

Environment: dev / asyncio / paper mode default
Phases: S-1 guard ordering · S-2 rollback atomicity · S-3 worker wiring · S-4 price_updater
        S-5 provider asymmetry (FLAG-2) · S-6 settlement gating · S-7 daily_loss_limit (FLAG-1) · S-8 coverage

---

## FINDINGS

### [S-1] LiveExecutionGuard — guard check ordering and raise contract

Evidence: server/core/live_execution_control.py

Check order confirmed:
1. kill_switch    L148  `if state.kill_switch:` → _block("kill_switch_active")
2. mode           L152  `if state.mode != "live":` → _block("mode_not_live")
3. env var        L159  `os.getenv("ENABLE_LIVE_TRADING",...) != "true"` → _block("enable_live_trading_not_set")
4. config.validate L166-171  CapitalModeGuardError → _block("capital_mode_guard_failed")
                              ValueError → _block("capital_mode_config_invalid")
5. provider       L174-178  None → _block("missing_financial_provider")
                  L183-194  try/except on field calls → _block("financial_provider_unavailable")
                  L196-205  all-zero → _block("financial_provider_all_zero")

WARNING log: _block() L216-222 always calls log.warning("live_execution_guard_blocked", reason, detail) before raise.

→ PASS — all 5 checks in declared order, correct reason strings, WARNING logs confirmed on every path.

### [S-2] disable_live_execution() — rollback atomicity

Evidence: server/core/live_execution_control.py:75-108

L93  `prior = state.kill_switch`           — pre-rollback state captured first
L94  `state.kill_switch = True`            — set before return
L95  `state.last_risk_reason = f"rollback:{reason}"` — set before return
L96-100  RollbackState(reason, detail, prior_kill_switch=prior)
L101-107  log.warning("live_execution_disabled", ...) — structured log
L94-L95: both simple attribute assignments; no exception source between them;
asyncio single-threaded — no race condition possible.

→ PASS — atomicity safe for single-threaded asyncio. prior_kill_switch captured correctly.

### [S-3] PaperBetaWorker.run_once() — live guard wiring

Evidence: server/workers/paper_beta_worker.py

Guard-injected path (L62-79):
  L63-65  resolved_provider = injected provider OR PortfolioFinancialProvider(STATE) as fallback
  L67     self._live_guard.check(STATE, provider=resolved_provider) — check #5 exercised — FLAG-3 CLOSED
  L68-79  LiveExecutionBlockedError caught → sets last_risk_reason, disable_live_execution(), `continue` — CLEAN SKIP

No-guard path (L80-94):
  L82     STATE.last_risk_reason = "mode_live_no_guard_injected"
  L89-93  disable_live_execution("no_live_guard_injected")
  L94     `continue` — CLEAN SKIP, no propagation

Post-loop guard (L148-155):
  `if STATE.mode == "live":` → price_updater skipped entirely, worker returns cleanly
  paper mode: price_updater called normally

→ PASS — wiring correct, both live paths deterministic and clean, no crash path in worker loop.

### [S-4] PaperBetaWorker.price_updater() — live mode block

Evidence: server/workers/paper_beta_worker.py:191-216

L200  `if STATE.mode == "live":` — guard fires
L213  disable_live_execution() — rollback triggered BEFORE raise
L214  raise LiveExecutionBlockedError — after rollback, reason="price_updater_stub_live_mode_blocked"
L215-216  paper mode: `await asyncio.sleep(0)` — safe no-op, no raise, no side effect
Worker-loop protection: run_once() L148-155 skips this call in live mode; direct invocation still raises.

→ PASS — direct call raises in live mode, rollback precedes raise, paper no-op confirmed.

### [S-5] PortfolioFinancialProvider — stub guard asymmetry (FLAG-2)

Evidence: server/risk/portfolio_financial_provider.py

get_balance_usd()  L75   calls _assert_not_stub(wallet_id, "balance_usd", wallet_equity) — GUARDED
get_exposure_pct() L84   NO _assert_not_stub() call — UNGUARDED
get_drawdown_pct() L101  NO _assert_not_stub() call — UNGUARDED

Analysis:
- Zero exposure in live mode is VALID: no open positions = 0% exposure
- Zero drawdown in live mode is VALID: no realized loss = 0% drawdown
- LiveExecutionGuard check #5 uses ALL-THREE-ZERO threshold (live_execution_control.py:196-200):
  abs(balance) < 1e-9 AND abs(exposure) < 1e-9 AND abs(drawdown) < 1e-9
  If wallet_equity is non-zero, all-zero guard does not fire regardless of exposure/drawdown.
- CapitalRiskGate reads drawdown/exposure from STATE directly (capital_risk_gate.py:169, 177),
  not from the provider — provider values serve only the LiveExecutionGuard stub readiness probe.

Verdict on FLAG-2: asymmetry is INTENTIONAL for NARROW INTEGRATION scope.
Zero exposure/drawdown are valid live states. All-zero guard in LiveExecutionGuard
covers the stub/uninitialized case when balance is also zero.
Document for P8-D: if a real multi-wallet live provider is built, add per-field
stub guards to get_exposure_pct() and get_drawdown_pct() at that point.

→ CONDITIONAL PASS — not a gap, intentional design; defer per-field guards to P8-D.

### [S-6] settlement_policy_from_capital_config() — gate coupling

Evidence: server/settlement/settlement_workflow.py:65-95

L82   `allowed = capital_config.is_capital_mode_allowed()` — single source of truth
L84-87 allow_real_settlement=allowed, simulation_mode=not allowed — derived from same flag; cannot diverge
SettlementWorkflowEngine.execute() L142-151: blocks with SETTLEMENT_STATUS_BLOCKED /
  blocked_reason="real_settlement_not_allowed" when allow_real_settlement is False in live mode.

→ PASS — allow_real_settlement coupled to capital gates; settlement blocked if gates off.

### [S-7] STATE.realized_pnl — daily_loss_limit permanent trip risk (FLAG-1)

Evidence: server/risk/capital_risk_gate.py:177, server/core/public_beta_state.py:45

capital_risk_gate.py:177  `if state.realized_pnl <= self._config.daily_loss_limit_usd:`
public_beta_state.py:45   `realized_pnl: float = 0.0` — single lifetime cumulative field
capital_risk_gate.py:205  label says "daily_pnl_usd" but value is lifetime — label/logic mismatch
No daily reset mechanism found anywhere in PublicBetaState, CapitalRiskGate, or worker loop.

Issue: daily_loss_limit_usd (default -$2000) is compared against lifetime cumulative realized_pnl.
Once cumulative losses exceed $2000 (paper or live), CapitalRiskGate blocks ALL new signals
permanently — no automatic reset at day boundary or session start.
Manual recovery requires operator kill_switch reset + realized_pnl manual reset to 0.0.
In live mode this means the daily circuit-breaker would never reset after first trip.

Classification: PRE-EXISTING BUG introduced in P8-B (declared in forge Known Issues).
Not introduced in P8-C. Does not affect P8-C guard contract claim (NARROW INTEGRATION).
HARD BLOCKER for P8-E capital validation and any live trading activation.

→ FAIL (pre-existing, declared) — hard blocker for P8-D/P8-E; not a P8-C critical issue.

### [S-8] Test coverage adequacy — CR-23..CR-36

Evidence: tests/test_capital_readiness_p8c.py

Guard checks (S-1): CR-23 kill_switch, CR-24×4 non-live mode, CR-25 env flag, CR-26 gates off,
  CR-27 missing provider, CR-28 all-zero provider, CR-29 gates on passes → COVERED
Provider exception normalization (new): CR-36, CR-36b — MissingRealFinancialDataError and
  RuntimeError both normalized to LiveExecutionBlockedError(reason="financial_provider_unavailable") → COVERED
Rollback (S-2): CR-30, CR-30b → COVERED
Worker wiring (S-3/S-4): CR-31 price_updater raises+rollback, CR-32 run_once clean return → COVERED
Provider (S-5): CR-33, CR-33b, CR-34, CR-34b → COVERED
Settlement (S-6): CR-35, CR-35b, CR-35c, CR-35d → COVERED
Regression: CR-regression import guard → COVERED

FLAG-1 permanent-trip scenario: no test — acceptable, pre-existing P8-B issue outside P8-C scope.
FLAG-2 exposure/drawdown asymmetry: no specific test — acceptable, intentional design.

→ PASS — 25/25 P8-C test cases cover all critical paths in scope.

---

## STABILITY SCORE

| Component      | Weight | Score | Notes |
|---|---|---|---|
| Architecture   | 20%    | 18/20 | Sound 5-gate design, provider normalization, clean guard/rollback/worker separation |
| Functional     | 20%    | 17/20 | All paths pass; FLAG-2 intentional asymmetry documented |
| Failure Modes  | 20%    | 18/20 | Provider exception normalization, fail-closed, kill_switch propagation all correct |
| Risk           | 20%    | 10/20 | FLAG-1: daily_loss_limit uses lifetime realized_pnl — circuit-breaker broken (pre-existing P8-B) |
| Infra+Telegram | 10%    |  7/10 | Not in P8-C scope; gate contract only |
| Latency        | 10%    |  8/10 | Not in P8-C scope |

**Total: 78/100**

---

## CRITICAL ISSUES

None within P8-C scope.

FLAG-1 (daily_loss_limit lifetime PnL) is a pre-existing P8-B bug, declared in forge Known Issues,
not introduced in P8-C, and does not affect the P8-C guard contract claim (NARROW INTEGRATION).
Classified as HARD BLOCKER for P8-D/P8-E — not a P8-C critical issue.

---

## GO-LIVE STATUS

**VERDICT: CONDITIONAL**
Score: 78/100. Critical: 0.

Reasoning:
- P8-C claim (NARROW INTEGRATION) validated: 5-gate guard, provider wiring, exception normalization,
  deterministic worker block, settlement gating all correct.
- Test coverage 25/25 P8-C (CR-23..CR-36), all critical guard paths covered.
- Two flags carried forward, not blocking at this claim level:
  - FLAG-1 daily_loss_limit: HARD BLOCKER for live trading — fix required in P8-D before P8-E sign-off.
  - FLAG-2 provider asymmetry: intentional; document for P8-D multi-wallet review.
- WARP🔹CMD review required before merge.

---

## PR GATE RESULT

| Gate | Status |
|---|---|
| Phase 0 pre-flight | PASS |
| S-1 guard check ordering | PASS |
| S-2 rollback atomicity | PASS |
| S-3 worker live guard wiring (FLAG-3 closed) | PASS |
| S-4 price_updater live mode block | PASS |
| S-5 provider asymmetry (FLAG-2) | CONDITIONAL PASS — intentional, P8-D review |
| S-6 settlement gate coupling | PASS |
| S-7 daily_loss_limit permanent trip (FLAG-1) | FAIL — pre-existing P8-B bug, P8-D/P8-E blocker |
| S-8 test coverage | PASS |
| Overall | CONDITIONAL — 78/100, 0 critical |

---

## FIX RECOMMENDATIONS

1. [HARD STOP — pre-P8-E, before any live capital activation]
   Fix daily_loss_limit to use day-scoped PnL.
   - Add `daily_realized_pnl: float = 0.0` to PublicBetaState (public_beta_state.py)
   - Add daily reset logic (at session start or day boundary)
   - Update CapitalRiskGate.evaluate() to compare `state.daily_realized_pnl` instead of `state.realized_pnl`
   - Fix status() report field label from "daily_pnl_usd" to match actual field used
   - Files: server/core/public_beta_state.py, server/risk/capital_risk_gate.py

2. [P8-D — if real multi-wallet live provider is built]
   Add per-field stub guards to get_exposure_pct() and get_drawdown_pct()
   in PortfolioFinancialProvider when replacing the single-wallet STATE-backed implementation.
   File: server/risk/portfolio_financial_provider.py

3. [P8-D] Build real WalletFinancialProvider backed by live market data feed.
   Current PortfolioFinancialProvider is single-wallet, in-memory only.

4. [P8-E] Implement real CLOB execution engine before setting EXECUTION_PATH_VALIDATED=true.

---

## DEFERRED BACKLOG

- Real CLOB order submission — P8-C guard blocks at worker level; no real orders possible
- Real market data feed — price_updater stub raises in live mode; stale PnL accepted for paper
- Per-user capital isolation — PublicBetaState is single-wallet; deferred to P8-D
- Telegram risk alert wiring for CapitalRiskGate.status() — deferred to P8-D
- EXECUTION_PATH_VALIDATED=true — must not be set until real CLOB path validated
- CAPITAL_MODE_CONFIRMED=true — must not be set until P8-E sign-off complete

---

## TELEGRAM PREVIEW

P8-C does not add new Telegram commands or alert events.
Existing kill_switch Telegram command reaches STATE.kill_switch and remains functional.
New structured log events available for operator monitoring (not wired to Telegram in this PR):
  - live_execution_guard_blocked (reason, detail)
  - live_execution_disabled (reason, prior_kill_switch)
  - paper_beta_worker_live_no_guard (signal_id)
  - paper_beta_worker_price_updater_skipped_live_mode (mode, kill_switch)

---

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Head: c12805f3ca (WARP/capital-readiness-p8c-2a76)
- NEXT GATE: Return to WARP🔹CMD for final merge decision.
