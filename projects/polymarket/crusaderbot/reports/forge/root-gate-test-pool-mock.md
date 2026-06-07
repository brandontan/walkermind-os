# WARP•R00T FORGE REPORT — root-gate-test-pool-mock

Branch: `WARP/root-gate-test-pool-mock`
Role: WARP•R00T (owner-directed 2026-06-08 — "separate R00T lane" for the #1694 CI regression)
Validation Tier: **MINOR** (test-only; mocks a DB helper, zero runtime/risk-logic change)
Claim Level: FOUNDATION
Validation Target: Restore green CI on `main` by mocking the gate's `_capital_alloc_pct` (a DB-reading helper added by #1694) in the two gate test files that #1694 left unpatched, so the 6 affected tests stop hitting the real Postgres pool under CI (which has no DB).
Not in Scope: any change to `domain/risk/gate.py` logic, risk constants, or other tests; the WARP-85 lane (#1696).
Suggested Next Step: merge to restore `main` green, then update/rebase WARP-85 (#1696) so its CI clears.

---

## 1. What was built

A test-only fix for a pre-existing CI regression. PR #1694 (risk-profile-capital)
added `_capital_alloc_pct()` — which calls `get_pool()` — into the gate step-8
deployment-cap path, and mocked it in `test_risk_limit_reconciliation.py` +
`test_resume_safety_check.py`, but **not** in the two other gate test files that
drive `gate.evaluate()`. Those 6 tests therefore reached the real DB pool under
CI (which runs `pytest tests/` with no Postgres / no `DATABASE_URL`) and failed
with `RuntimeError: Database pool not initialised`. CI on `main` has been RED
since #1694 (#1693 was the last green commit; #1694 and #1695 both show failure).

Fix — mirror #1694's established mock pattern:
- `tests/test_concurrency_policy.py` `_patch_clear`: added a `capital_alloc_pct=0.40`
  param + `monkeypatch.setattr(gate_mod, "_capital_alloc_pct", AsyncMock(...))`
  (covers the 4 failing `evaluate`/resume tests).
- `tests/test_complete_set_scan.py` `_patch_gate_passthrough`: added an async
  `_cap` returning 0.40 + `monkeypatch.setattr(gate_mod, "_capital_alloc_pct", _cap)`
  (covers the 2 failing complete-set tests; their own comments already note
  "passes step 8" at 0.09 exposure, so 0.40 clears them).

## 2. Current system architecture

No runtime change. Only the two test helpers gain a mock for the gate's
`_capital_alloc_pct`, identical in spirit to the mocks already present for
`_open_exposure`, `get_balance`, `daily_pnl`, etc. The gate itself is untouched.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/tests/test_concurrency_policy.py`
- `projects/polymarket/crusaderbot/tests/test_complete_set_scan.py`
- state: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`

## 4. What is working

- The 6 previously-failing tests now pass (35 passed across the two files).
- Full suite: **3053 passed**, 9 skipped; the remaining 8 failures are
  environmental dep-missing only (`test_clob_pysdk`, `test_builder_relayer`,
  `test_wallet_safe` — `poly_eip712_structs` / `eth_account` absent in the
  sandbox but installed in CI). The 6 DB-pool failures are gone → CI goes green.
- ruff clean.

## 5. Known issues

- The 8 dep-missing failures are sandbox-only (CI installs those optional SDKs).
  Not addressed here — orthogonal to the CI regression and out of scope.

## 6. What is next

Merge to restore `main` green. Then update WARP-85 (#1696) onto the new `main`
so its `Lint + Test` clears (it inherited this same red CI).

---

Validation Tier: MINOR
Claim Level: FOUNDATION
Validation Target: 6 gate tests no longer hit the real DB pool; CI green.
Not in Scope: gate logic, risk constants, WARP-85.
Suggested Next Step: WARP🔹CMD review / R00T self-merge → update #1696.
