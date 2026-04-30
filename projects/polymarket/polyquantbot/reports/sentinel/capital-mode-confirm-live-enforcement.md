# WARP•SENTINEL Report — capital-mode-confirm-live-enforcement

**Branch:** WARP/capital-mode-confirm
**PR:** #818
**Validated by:** WARP•SENTINEL
**Date:** 2026-04-30 15:19 (Asia/Jakarta)
**Validation Tier:** MAJOR
**Claim Level:** LIVE INTEGRATION
**Source forge report:** projects/polymarket/polyquantbot/reports/forge/capital-mode-confirm.md

---

## Environment

| Item | Value |
|---|---|
| Python | 3.12.3 |
| pytest | 9.0.3 |
| Runner locale | UTF-8 |
| Branch verified | WARP/capital-mode-confirm (PR #818 head) |
| Forge report | Exists at declared path, all 6 sections present |
| PROJECT_STATE.md | Updated — Last Updated 2026-04-30 16:10 |

---

## Validation Context

Tier: MAJOR — LIVE INTEGRATION

Claim: `check_with_receipt()` is the only admitted path for live capital execution at two production call sites:
- `ClobExecutionAdapter.submit_order()` — `mode='live'` construction fails fast without `confirmation_store`
- `PaperBetaWorker.run_once()` — `confirmation_store is None` triggers `disable_live_execution()`

Additionally: `CapitalModeRevokeFailedError` raised on DB persistence failure; `/beta/capital_mode_revoke` returns HTTP 503 with warning field.

Not in Scope: setting any env gate; live trading flip; multi-replica Redis; deferred items from PR #813 SENTINEL.

---

## Phase 0 Checks

| Check | Result |
|---|---|
| Forge report at declared path — 6 sections present | PASS |
| PROJECT_STATE.md updated with full timestamp (2026-04-30 16:10) | PASS |
| py_compile — all 6 touched Python files | PASS |
| No phase*/ folders | PASS |
| No hardcoded secrets in diff | PASS |
| No threading imports in touched files | PASS |
| KELLY_FRACTION = 0.25 (capital_mode_config.py:46) | PASS |
| MAX_POSITION_FRACTION_CAP = 0.10 (capital_mode_config.py:47) | PASS |
| DRAWDOWN_LIMIT_CAP = 0.08 (capital_mode_config.py:48) | PASS |
| _DEFAULT_DAILY_LOSS_LIMIT_USD = -2000.0 (capital_mode_config.py:55) | PASS |
| MIN_LIQUIDITY_USD_FLOOR = 10000.0 (capital_mode_config.py:49) | PASS |
| ENABLE_LIVE_TRADING guard not bypassed in any new code path | PASS |
| EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / ENABLE_LIVE_TRADING — NOT SET in diff | PASS |

Phase 0: **ALL PASS**

---

## Findings

### S-1: ClobExecutionAdapter — no bypass path exists

**S-1a: mode='live' + confirmation_store=None → ValueError at __init__**

Verified at `clob_execution_adapter.py:249-256`:

```python
if mode == "live" and confirmation_store is None:
    raise ValueError(
        "ClobExecutionAdapter mode='live' requires confirmation_store; "
        "constructing without it would bypass the P8-E receipt layer ..."
    )
```

Test P8E-18 passes: `ClobExecutionAdapter(config, client, mode="live", confirmation_store=None)` → `ValueError` with `"confirmation_store"` and `"P8-E receipt layer"` in message. **VERIFIED.**

**S-1b: confirmation_store is not None → submit_order calls check_with_receipt() only**

Verified at `clob_execution_adapter.py:302-311`:

```python
if self._confirmation_store is not None:
    await self._guard.check_with_receipt(
        state,
        store=self._confirmation_store,
        provider=provider,
        wallet_id=wallet_id,
    )
else:
    self._guard.check(state, provider=provider, wallet_id=wallet_id)
```

When `confirmation_store` is wired (required for `mode='live'`), only `check_with_receipt()` runs — no fallback to sync `check()` on the live path. **VERIFIED.**

**S-1c: mode='mocked' → allowed without store (test path)**

`mode='mocked'` skips the ValueError guard (line 249 checks `mode == "live"` only). All RCLOB tests (1-23, 25-30) use `mode="mocked"` without a store. Test execution passes. **VERIFIED.**

**S-1d: No instantiation site passes mode='live' without confirmation_store**

Full codebase scan (`grep -rn "ClobExecutionAdapter("`) shows:
- `mock_clob_client.py:10` — `mode="mocked"` (no store needed)
- `test_real_clob_execution_path.py` — all 19 non-P8E-18 instantiations use `mode="mocked"`
- `test_capital_readiness_p8e.py:705` — P8E-18 deliberately uses `mode="live"` without store to verify the ValueError; this is a break-attempt test, not a production path
- `test_capital_readiness_p8e.py:749` — P8E-19 uses `mode="live"` with store wired (correct live path test)
- `run_worker_loop()` in paper_beta_worker.py — constructs no adapter; worker loop is paper-only
- No production instantiation of `mode='live'` without store found anywhere in server/ **VERIFIED.**

---

### S-2: PaperBetaWorker — live path ordering correct

**S-2a: Guard order in run_once()**

Verified at `paper_beta_worker.py:85-147`:

1. `STATE.mode != "paper"` check (line 85) — enters live path
2. `self._live_guard is None` → `disable_live_execution(reason="no_live_guard_injected")` + `continue` (lines 92-106)
3. `self._confirmation_store is None` → `disable_live_execution(reason="no_confirmation_store_injected")` + `continue` (lines 107-126)
4. `await self._live_guard.check_with_receipt(...)` (lines 131-135)

Order is: live_guard-None → confirmation_store-None → check_with_receipt. **VERIFIED.**

**S-2b: disable_live_execution() called (not just continue) on confirmation_store=None**

Line 118-125: `disable_live_execution(STATE, reason="no_confirmation_store_injected", detail=...)` is called before `continue`. This halts live mode state (sets `kill_switch=True` via `disable_live_execution`), not just skips the candidate.

Test P8E-16: asserts `state.kill_switch is True` and `"no_confirmation_store_injected" in state.last_risk_reason` after run_once(). **VERIFIED.**

**S-2c: check_with_receipt() is awaited correctly**

Line 131: `await self._live_guard.check_with_receipt(...)` — async guard in the candidate loop. `check_with_receipt` is `async def` at `live_execution_control.py:217`. **VERIFIED.**

**S-2d: No fallback to check() in the live worker path**

The live path (lines 85-147) uses only `check_with_receipt()` — the synchronous `check()` is never called when `STATE.mode != "paper"` and stores are wired. No `self._live_guard.check(...)` call exists in the live branch. **VERIFIED.**

---

### S-3: CapitalModeRevokeFailedError — incident response integrity

**S-3a: revoke_latest() — active row found + DB UPDATE fails → raises CapitalModeRevokeFailedError**

Verified at `capital_mode_confirmation_store.py:146-175`:

```python
active = await self.get_active(mode)
if active is None:
    return None  # no-active case preserved
ok = await self._db._execute(sql, ..., op_label="capital_mode_confirm_revoke")
if not ok:
    raise CapitalModeRevokeFailedError(
        f"capital_mode_confirmations UPDATE failed for "
        f"confirmation_id={active.confirmation_id!r}; active receipt may still be in force"
    )
```

Test P8E-20: seeds an active row, sets `db.fail_execute = True`, asserts `CapitalModeRevokeFailedError` raised with `"may still be in force"` in message. **VERIFIED.**

**S-3b: Route /beta/capital_mode_revoke catches CapitalModeRevokeFailedError → HTTP 503 with warning field**

Verified at `public_beta_routes.py:536-551`:

```python
except CapitalModeRevokeFailedError as exc:
    raise HTTPException(
        status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "outcome": "persistence_failed",
            "reason": "capital_mode_revoke_persistence_failed",
            "detail": str(exc),
            "warning": "active capital_mode receipt may still be in force; retry revoke or halt via kill switch",
        },
    )
```

`"warning"` field exact value matches SENTINEL task specification. Test P8E-21 asserts `resp.status_code == 503`, `detail["outcome"] == "persistence_failed"`, `detail["reason"] == "capital_mode_revoke_persistence_failed"`, `"may still be in force" in detail["warning"]`. **VERIFIED.**

**S-3c: None return path preserved for "no active row" case**

Line 148: `if active is None: return None`. Distinct from DB failure path (CapitalModeRevokeFailedError). Test P8E-05 verifies `revoke_latest()` returns `None` when no active row exists. Route at `public_beta_routes.py:552-562` returns `{"ok": False, "stage": "no_active", ...}` for `None` result. **VERIFIED.**

---

### S-4: New tests — coverage completeness

| Test | Result |
|---|---|
| P8E-16: worker live without store → disabled with disable_live_execution | PASS |
| P8E-17: worker live with store, no receipt → check_with_receipt raises, disable called | PASS |
| P8E-18: ClobExecutionAdapter(mode=live, store=None) → ValueError | PASS |
| P8E-19: ClobExecutionAdapter(mode=live, store=wired, receipt=active) → submit proceeds | PASS |
| P8E-20: store.revoke_latest() DB fail → raises CapitalModeRevokeFailedError | PASS |
| P8E-21: POST /beta/capital_mode_revoke DB fail → HTTP 503 | PASS |
| RCLOB-24: run_once() injects receipt store + live path exercised end-to-end | PASS |

All 21/21 P8E tests + 30/30 RCLOB tests confirmed passing locally. **VERIFIED.**

---

### S-5: Risk constants — unchanged

| Constant | Value in diff | Expected | Status |
|---|---|---|---|
| KELLY_FRACTION | 0.25 (capital_mode_config.py:46) | 0.25 | PASS |
| MAX_POSITION_FRACTION_CAP | 0.10 (capital_mode_config.py:47) | <=10% | PASS |
| DRAWDOWN_LIMIT_CAP | 0.08 (capital_mode_config.py:48) | 8% | PASS |
| _DEFAULT_DAILY_LOSS_LIMIT_USD | -2000.0 (capital_mode_config.py:55) | -$2000 | PASS |
| MIN_LIQUIDITY_USD_FLOOR | 10000.0 (capital_mode_config.py:49) | $10k | PASS |
| ENABLE_LIVE_TRADING guard | Not bypassed — checked in check() at live_execution_control.py | intact | PASS |

RCLOB-30 confirms KELLY_FRACTION == 0.25 at test time. **VERIFIED.**

---

### S-6: No new env var set

Diff scan confirms:
- EXECUTION_PATH_VALIDATED — referenced in docs/comments only; not set in any new code path
- CAPITAL_MODE_CONFIRMED — referenced in docs/comments only; not set in any new code path
- ENABLE_LIVE_TRADING — referenced in docs/comments only; not set in any new code path

No `os.environ[...] =` or `os.putenv(...)` calls in any new production code. PROJECT_STATE.md explicitly states all three are `NOT SET`. **VERIFIED.**

---

## Score Breakdown

| Criterion | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 20/20 | Defence-in-depth: env-var layer + DB-receipt layer; no bypass path at constructor or runtime |
| Functional | 20% | 20/20 | All 6 declared claims verified with file+line evidence; 21/21 P8E + 30/30 RCLOB passing |
| Failure modes | 20% | 19/20 | P8E-16/17 worker blocks correctly; P8E-20/21 revoke-fail 503 correct; -1 for worker having no constructor-time guard (run_once-time only, noted as known issue) |
| Risk | 20% | 20/20 | All 5 risk constants intact; ENABLE_LIVE_TRADING guard not bypassed; no env var set |
| Infra + Telegram | 10% | 9/10 | Pending-token store is in-process (single-replica acceptable per runbook); revoke route returns 503 with warning; -1 for no live PostgreSQL integration test (unit tests only) |
| Latency | 10% | 10/10 | No new blocking I/O in hot paths; check_with_receipt is fully async; DB receipt lookup is one indexed SELECT |

**Total: 98/100**

---

## Critical Issues

None found.

---

## Status

**GO-LIVE: APPROVED**

Score 98/100. Zero critical issues. All S-1 through S-6 checklist items verified with file+line evidence.

The `mode='live'` fail-fast at construction (`ValueError`) and the `disable_live_execution()` at runtime on missing store provide defence-in-depth against misconfiguration. The revoke 503 path correctly distinguishes DB failure from no-active-receipt, protecting operators from false "nothing to revoke" responses during incident response.

---

## PR Gate Result

APPROVED. PR #818 is safe to merge after WARP🔹CMD review.

- Forge report matches implemented code
- 21/21 P8E + 30/30 RCLOB tests passing
- Risk constants unchanged
- No env gate set in code
- No critical findings

---

## Broader Audit Finding

No broader systemic issues found in the diff scope.

The known issue from previous SENTINEL (PR #813 F-1 — `run_once price_updater() skipped in live mode`) is still present and correctly handled: the worker logs `paper_beta_worker_price_updater_skipped_live_mode` and skips the call rather than raising. This is the correct mitigation per the deferred-fix status in PROJECT_STATE.md. No regression introduced by this PR.

---

## Reasoning

Claim level LIVE INTEGRATION is justified and substantiated:

1. **Constructor-time guard** — `mode='live'` raises `ValueError` without store (not a runtime soft block, a hard construction-time refusal)
2. **Runtime guard** — `PaperBetaWorker.run_once()` calls `disable_live_execution()` (state-level halt, not just skip) when store is absent
3. **No bypass path** — no production code instantiates `ClobExecutionAdapter(mode='live', confirmation_store=None)` anywhere in the codebase
4. **Revoke integrity** — `CapitalModeRevokeFailedError` is distinct from `None` return; the 503 route makes the distinction operator-visible
5. **Test coverage** — P8E-16 through P8E-21 are direct break-attempt tests, not just happy-path tests

---

## Fix Recommendations

None required for merge.

Advisory (non-blocking):

1. **Worker constructor guard** — consider adding a `ValueError` in `PaperBetaWorker.__init__()` when `mode='live'` is desired but `confirmation_store=None`. Currently the block is at `run_once()` time. The current approach is safe (fail-closed) but constructor-time fail-fast would be more symmetrical with `ClobExecutionAdapter`. Defer to a future WARP•FORGE pass.

2. **Multi-replica token store** — `_PENDING_CAPITAL_CONFIRMS` is in-process. Safe for current single-Fly-machine deployment (per runbook §2). Redis-backed swap required before horizontal scale. Already in `[KNOWN ISSUES]`.

---

## Out-of-scope Advisory

The following were NOT in scope and were not validated:

- Deferred items from PR #813 SENTINEL (MockClobMarketDataClient protocol tightening, AiohttpClobClient build, order dedup persistence)
- Priority 9 launch assets, public-product completion, handoff
- Live PostgreSQL / Redis integration tests
- Multi-replica token store swap

---

## Deferred Minor Backlog

- [DEFERRED] Worker constructor-time guard for `confirmation_store=None` when live mode intended — found in PR #818 validation. Non-critical; `run_once()` enforcement is correct fail-closed behaviour.

---

## Telegram Visual Preview

**Dashboard display (after /capital_mode_confirm two-step):**

```
CrusaderBot Capital Gate
========================
Mode: LIVE
Kill Switch: OFF
Capital Mode: AUTHORIZED (2-layer)
  Layer 1 (env): ✅ ENABLE_LIVE_TRADING + 4 gates SET
  Layer 2 (receipt): ✅ Active confirmation in DB
  Confirmed by: operator_id
  Confirmed at: YYYY-MM-DD HH:MM UTC
  Revoke: /capital_mode_revoke
```

**Alert on revoke persistence failure:**

```
🚨 CAPITAL MODE REVOKE FAILED
Outcome: persistence_failed
Warning: active capital_mode receipt may still be in force
Action required: retry /capital_mode_revoke or activate kill switch immediately
```

**Alert on worker blocked (missing store):**

```
⛔ LIVE EXECUTION BLOCKED
Reason: no_confirmation_store_injected
P8-E receipt layer cannot be enforced in live mode
Capital execution halted — check wiring and restart
```

