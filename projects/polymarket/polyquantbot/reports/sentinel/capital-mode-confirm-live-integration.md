# WARP•SENTINEL Report — capital-mode-confirm-live-integration

**Branch:** WARP/capital-mode-confirm
**PR:** #818
**Validated by:** WARP•SENTINEL
**Timestamp:** 2026-04-30 15:19 (Asia/Jakarta)
**Validation Tier:** MAJOR
**Claim Level:** LIVE INTEGRATION

---

## Environment

- Runner: cloud agent, /workspace
- Python: 3.12.3
- pytest: 9.0.3
- Source: projects/polymarket/polyquantbot/reports/forge/capital-mode-confirm.md
- Branch verified: WARP/capital-mode-confirm (PR #818 head)
- PR #813 (WARP/real-clob-execution-path) merge confirmed: merged 2026-04-30T05:25:43Z (state: MERGED)

---

## Validation Context

**Claim Level:** LIVE INTEGRATION — strict enforcement of `check_with_receipt()` at both production live call sites.
**Validation Target:** (1) ClobExecutionAdapter constructor breaking change; (2) PaperBetaWorker.run_once() live guard rewrite; (3) CapitalModeRevokeFailedError incident path; (4) P8E-16..P8E-21 + rclob_24; (5) No regression paths; (6) Forge report accuracy.
**Not in Scope:** Setting env vars; flipping live trading; deferred PR #813 SENTINEL items; Priority 9; multi-replica Redis store.

---

## Phase 0 Checks

- [x] Forge report exists at `projects/polymarket/polyquantbot/reports/forge/capital-mode-confirm.md` — all 6 sections present
- [x] PROJECT_STATE.md updated — Last Updated: 2026-04-30 16:10, full timestamp
- [x] py_compile passes: clob_execution_adapter.py, paper_beta_worker.py, capital_mode_confirmation_store.py, public_beta_routes.py, live_execution_control.py, test_capital_readiness_p8e.py, test_real_clob_execution_path.py — all PASS
- [x] No phase*/ folders in projects/polymarket/polyquantbot/ — confirmed clean
- [x] No hardcoded secrets or API keys — confirmed; all read from env via os.getenv
- [x] No threading import — asyncio only throughout all touched files
- [x] Risk constants intact — KELLY_FRACTION = 0.25 (signal_engine.py), kelly_fraction=1.0 raises ValueError (P8A CR-07), RCLOB-30 asserts 0.25
- [x] ENABLE_LIVE_TRADING guard not bypassed — verified at live_execution_control.py:160 (check()) and propagated through check_with_receipt() at line 242

---

## Findings

### 1. ClobExecutionAdapter constructor — breaking change audit

**1a. mode=live + confirmation_store=None raises ValueError — not swallowed upstream**
- `clob_execution_adapter.py:249-256`: Constructor raises `ValueError` at `__init__` immediately when `mode='live'` and `confirmation_store is None`.
- Error message: "ClobExecutionAdapter mode='live' requires confirmation_store; constructing without it would bypass the P8-E receipt layer..."
- The ValueError is raised before any state is stored — it propagates to the caller and cannot be swallowed silently.
- Test P8E-18 verifies: `pytest.raises(ValueError)` with `"confirmation_store" in str(exc_info.value)` — PASS.
- **APPROVED**

**1b. ALL callers of ClobExecutionAdapter — none call mode=live without confirmation_store**
- rg scan of entire polyquantbot/ for `ClobExecutionAdapter`: all non-test callers use `mode="mocked"` or accept `mode` default parameter.
- test_real_clob_execution_path.py lines 208..456: all 22+ instantiation points use `mode="mocked"`.
- rclob_24 (line 633): `ClobExecutionAdapter(config=cfg, client=mock_client, mode="mocked")` — mocked, store not required.
- mock_clob_client.py docstring (line 10): shows `mode="mocked"` as example.
- PaperBetaWorker: accepts `ClobExecutionAdapter` as an injected dependency — does not construct it. The caller of `PaperBetaWorker` is responsible for passing a correctly-constructed adapter.
- run_worker_loop() (paper_beta_worker.py:382): constructs `PaperBetaWorker` without `clob_adapter` arg — paper mode only, no live adapter constructed.
- **APPROVED**

**1c. submit_order() else branch only reachable from mode=mocked**
- `clob_execution_adapter.py:302-311`: `if self._confirmation_store is not None: await check_with_receipt(...)` else `self._guard.check(...)`.
- The `else` branch (sync `check()`) executes only when `self._confirmation_store is None`.
- `self._confirmation_store is None` is only possible when `mode='mocked'` at construction (because `mode='live'` without store raises ValueError at `__init__`).
- Therefore the else branch is structurally unreachable from any production live path.
- **APPROVED**

### 2. PaperBetaWorker.run_once() — live guard rewrite

**2a. Execution order correct: live_guard=None block first, store=None second, check_with_receipt third**
- `paper_beta_worker.py:85-146`: for each candidate when `STATE.mode != "paper"`:
  1. Line 92-106: `if self._live_guard is None` → disable + continue (live_guard=None block)
  2. Line 107-126: `if self._confirmation_store is None` → disable with `no_confirmation_store_injected` + continue
  3. Line 130-147: `await self._live_guard.check_with_receipt(STATE, store=self._confirmation_store, provider=resolved_provider)` — no fallback
- Order confirmed correct. No fallback to sync `check()` when store is wired.
- **APPROVED**

**2b. disable_live_execution() on confirmation_store=None sets kill_switch=True**
- `paper_beta_worker.py:118-126`: calls `disable_live_execution(STATE, reason="no_confirmation_store_injected", ...)`.
- `live_execution_control.py:95`: `state.kill_switch = True`.
- `live_execution_control.py:96`: `state.last_risk_reason = f"rollback:{reason}"`.
- P8E-16 test (line 609-611): asserts `state.kill_switch is True` AND `"no_confirmation_store_injected" in state.last_risk_reason` — PASS.
- **APPROVED**

**2c. check_with_receipt() called without wallet_id — signature accepts optional wallet_id**
- `live_execution_control.py:219`: `async def check_with_receipt(self, state, store, provider=None, wallet_id=_STUB_WALLET_ID)` — `wallet_id` has default `_STUB_WALLET_ID = "__readiness_probe__"`.
- Worker call at paper_beta_worker.py:131-135: `await self._live_guard.check_with_receipt(STATE, store=self._confirmation_store, provider=resolved_provider)` — no wallet_id arg; default used correctly.
- **APPROVED**

**2d. Paper mode (STATE.mode==paper) bypasses live guard entirely — verified unchanged**
- `paper_beta_worker.py:85`: `if STATE.mode != "paper":` — the entire live-guard block is inside this conditional. When mode is paper, code skips directly to autotrade/kill_switch checks (line 149).
- P8E test (RCLOB-25): paper mode with adapter wired — paper engine called, clob client NOT called (mock_client.call_count == 0) — PASS.
- **APPROVED**

### 3. CapitalModeRevokeFailedError — incident path

**3a. revoke_latest() raises CapitalModeRevokeFailedError when active row found but DB write fails**
- `capital_mode_confirmation_store.py:146-175`: calls `get_active(mode)` first (line 146). If `active is None`, returns None (line 147-148). If active row found, attempts UPDATE (line 158). If `ok=False` (line 166), logs and raises `CapitalModeRevokeFailedError` (line 172-175).
- Error message includes: "active receipt may still be in force".
- **APPROVED**

**3b. /capital_mode_revoke catches CapitalModeRevokeFailedError → HTTP 503 with warning**
- `public_beta_routes.py:536-551`: `except CapitalModeRevokeFailedError as exc:` → raises HTTPException with `status_code=503` and `detail["warning"] = "active capital_mode receipt may still be in force; retry revoke or halt via kill switch"`.
- **APPROVED**

**3c. Old silent-None behavior on DB fail is GONE**
- Previous behavior (pre-PR): revoke persistence failure would return `None` or swallow exception, causing callers to believe revoke succeeded when it did not.
- Current code at line 166-175: explicitly raises `CapitalModeRevokeFailedError` — no fallthrough, no silent None return when active row exists and write fails.
- **APPROVED**

**3d. P8E-20 covers CapitalModeRevokeFailedError path**
- test_capital_readiness_p8e.py:775-802: P8E-20 inserts a row, sets `db.fail_execute=True`, then asserts `pytest.raises(CapitalModeRevokeFailedError)` with `"may still be in force" in str(exc_info.value)` — PASS.
- P8E-21 (line 805-836): full route-level 503 test, verifies `resp.status_code == 503`, `detail["outcome"] == "persistence_failed"`, `"may still be in force" in detail["warning"]` — PASS.
- **APPROVED**

### 4. P8E-16..P8E-21 + rclob_24 update

**4a. P8E-16: worker live without store → kill_switch=True + no_confirmation_store_injected**
- test_capital_readiness_p8e.py:537-611: worker constructed with `confirmation_store=None`, live_guard injected, live mode. `run_once()` returns empty list. `state.kill_switch is True`. `"no_confirmation_store_injected" in state.last_risk_reason`. PASS.
- **APPROVED**

**4b. P8E-17: worker live with store but no receipt → blocks with capital_mode_no_active_receipt**
- test_capital_readiness_p8e.py:614-687: store injected (empty DB), no row inserted. `run_once()` returns []. `state.kill_switch is True`. `"capital_mode_no_active_receipt" in state.last_risk_reason`. PASS.
- **APPROVED**

**4c. test_rclob_24: seed active receipt required — test fails without seed (seam is real)**
- test_real_clob_execution_path.py:619-632: explicit `confirmation_store.insert(...)` call seeds a receipt before worker is constructed. Without this seed, `check_with_receipt()` would call `store.get_active()`, get None, block with `capital_mode_no_active_receipt`, and return empty events — so rclob_24 would fail. The seam is real and enforced.
- **APPROVED**

**4d. All prior ClobExecutionAdapter(mode=live) callers updated to mode=mocked or pass store**
- Full rg scan: no production caller (outside test files) constructs `ClobExecutionAdapter(mode='live', ...)`. All 22+ test instantiations use `mode="mocked"`. P8E-19 constructs with `mode='live' + confirmation_store=store` (with seed receipt) as the only live-mode adapter test — passes.
- **APPROVED**

### 5. No regression paths

**5a. else branch in submit_order() only reachable from mode=mocked — confirmed**
- `clob_execution_adapter.py:302-311`: else only when `self._confirmation_store is None`, which is only possible if `mode='mocked'` at construction (live raises ValueError). Structurally enforced by constructor guard.
- **APPROVED**

**5b. Paper-mode path in paper_beta_worker: no live guard called, no store checked**
- `paper_beta_worker.py:85`: entire live guard block inside `if STATE.mode != "paper"`. Paper signals skip to line 149.
- **APPROVED**

**5c. test_real_clob_execution_path.py full suite: no test broken by constructor change**
- 30/30 RCLOB tests PASS. No test constructs `ClobExecutionAdapter(mode='live')` without store — all 30 tests use `mode="mocked"` or the seeded-store pattern (rclob_24).
- **APPROVED**

### 6. Forge report accuracy

**6a. Claim Level LIVE INTEGRATION matches diff — confirmed**
- The PR modifies runtime call sites (PaperBetaWorker.run_once() + ClobExecutionAdapter.submit_order()) to route through `check_with_receipt()`. This is live execution path behavior, not scaffold. LIVE INTEGRATION claim is accurate.
- **APPROVED**

**6b. PR #813 has already merged — verified**
- `gh pr view 813` returns: `state: MERGED`, `mergedAt: 2026-04-30T05:25:43Z`. PR #813 (WARP/real-clob-execution-path) is in main.
- Forge report states "PR #813 has already merged" in Not-in-Scope — accurate.
- **APPROVED**

**6c. Not-in-scope list — no deferred items accidentally in diff**
- Verified: no env var assignment, no ENABLE_LIVE_TRADING=true, no CAPITAL_MODE_CONFIRMED=true in diff. run_worker_loop() remains paper-only. AiohttpClobClient not present. Multi-replica Redis store not present. All deferred items confirmed absent from diff.
- **APPROVED**

---

## Score Breakdown

| Criterion | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 20/20 | Defence-in-depth: env gates + DB receipt. Constructor fail-fast. Structural enforcement. |
| Functional | 20% | 20/20 | 21/21 P8E + 30/30 RCLOB pass. All 6 SENTINEL items APPROVED. |
| Failure modes | 20% | 20/20 | No-store path → kill_switch. No-receipt path → kill_switch. DB revoke fail → 503. No silent fallback. |
| Risk | 20% | 20/20 | Kelly=0.25 constant. ENABLE_LIVE_TRADING guard not bypassed. No threading. No hardcoded secrets. |
| Infra + Telegram | 10% | 9/10 | Telegram confirm/revoke handlers wired. Store wired in main.py. -1 for in-process pending store (known, documented deferred). |
| Latency | 10% | 10/10 | No blocking I/O in hot path. Store lookup async. Guard chain is O(1) before DB call. |
| **Total** | | **99/100** | |

---

## Critical Issues

None found.

---

## Status

**APPROVED — Score: 99/100. Critical issues: 0.**

All 6 validation items per SENTINEL TASK brief: APPROVED.
All 167 regression tests: PASS.
Phase 0: all checks pass.
Claim Level LIVE INTEGRATION: substantiated.

---

## PR Gate Result

**APPROVED — PR #818 cleared for WARP🔹CMD merge decision.**

Forge report: projects/polymarket/polyquantbot/reports/forge/capital-mode-confirm.md
Sentinel report: projects/polymarket/polyquantbot/reports/sentinel/capital-mode-confirm-live-integration.md

---

## Broader Audit Finding

No broader audit findings. Scope was tightly controlled per SENTINEL TASK brief. No unrelated regressions detected across all touched area suites (167/167 pass).

---

## Reasoning

The PR activates a scaffold (PR #815 APPROVED 97/100) by wiring `check_with_receipt()` as the only authorized live-execution path. The two key properties that make this LIVE INTEGRATION secure:

1. **Constructor fail-fast:** `ClobExecutionAdapter(mode='live', confirmation_store=None)` raises `ValueError` at object construction — no runtime path can accidentally call `submit_order()` without the receipt layer.
2. **Worker defence-in-depth:** `PaperBetaWorker.run_once()` checks live_guard → store injection → check_with_receipt, in that order. Any gap triggers `disable_live_execution()` setting `kill_switch=True`.

The revoke 503 change closes the silent-failure incident gap: operators now receive a clear 503 with "active receipt may still be in force" rather than a misleading "nothing to revoke" response when DB write fails during a live-trading incident.

---

## Fix Recommendations

None — all items APPROVED.

---

## Out-of-scope Advisory

- In-process `_PENDING_CAPITAL_CONFIRMS` store (known issue, documented): Redis-backed swap before multi-replica horizontal scale.
- `run_once()` worker live path calls `disable_live_execution()` at runtime (fail-closed) rather than raising at construction when `confirmation_store=None`. A future improvement would mirror the adapter's constructor-time ValueError, but the current runtime fail-closed behavior is safe.
- These are advisory only — neither blocks merge.

---

## Deferred Minor Backlog

- `[DEFERRED]` In-process pending-token store (`_PENDING_CAPITAL_CONFIRMS`) — requires Redis swap before horizontal replica deployment. Non-critical for single-instance Fly runtime. Found in WARP/capital-mode-confirm (PR #818).
- `[DEFERRED]` PaperBetaWorker does not raise at construction when `confirmation_store=None` in live mode (defer to P9 hardening). Found in WARP/capital-mode-confirm (PR #818).

---

## Telegram Visual Preview

```
━━━━━━━━━━━━━━━━━━━━━━━━━
🔐 SENTINEL RESULT
PR: #818 — capital-mode-confirm LIVE INTEGRATION
━━━━━━━━━━━━━━━━━━━━━━━━━
Verdict:  APPROVED ✅
Score:    99 / 100
Critical: 0

Tests:    167 / 167 PASS
  P8E:    21 / 21
  RCLOB:  30 / 30
  P8A-D:  70 / 70
  P7+TG:  46 / 46

Phase 0:  ALL PASS ✅
Claim:    LIVE INTEGRATION — substantiated ✅

NEXT: Return to WARP🔹CMD for final merge decision.
WARP•SENTINEL does not merge.
━━━━━━━━━━━━━━━━━━━━━━━━━
```
