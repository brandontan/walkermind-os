# WARP•FORGE — case1-test-poll

Validation Tier: MINOR (staging test-only; no production code touched)
Claim Level: FOUNDATION
Validation Target: `test_case1_closing_rollback_on_cancelled_sell` tolerates the broker's eventually-consistent cancel by polling the closing sweep until rollback, so the real-broker rollback path is validated (closing the last all-broker red).
Not in Scope: any production code (`live_reconcile.py` / `complete_set_exec.py` unchanged — the conservative `pending`-until-terminal behavior is correct, per `case1-rollback-investigation.md`); LIVE flip (`allow_fills`/`ENABLE_LIVE_TRADING` stay gated).
Suggested Next Step: dispatched `all-broker` (nrt, `allow_fills=false`) on this branch's logic — expect TRUE 8/8.

## 1. What was built

A bounded poll for the case1 rollback assertion, applying the recommendation from the case1 investigation report. The cancel in `test_case1_closing_rollback_on_cancelled_sell` is eventually-consistent on the real broker, so a single immediate `reconcile_closing_positions` call legitimately reads the just-cancelled close order as still-`LIVE` and returns the conservative `pending` (by design). The test now polls.

New helper `_poll_closing_rollback(pool, *, tries=10, delay=1.5)` mirrors `_poll_open_order` EXACTLY (same tries/delay budget = case3 consistency): it re-runs the closing sweep until `rolled_back >= 1` or the budget is exhausted, tolerating transient read errors per tick. The `_Conn` fake returns the static closing row on every `fetch`, so each tick re-queries the real broker — once the cancellation settles to a terminal `get_order` status (which `_KILLED_STATUSES` already maps to `FILL_KILLED`), the sweep rolls back and the poll returns.

No production change: `reconcile_closing_positions` + `_fill_status` already handle terminal `CANCELED` correctly; the only gap was the test asserting an immediate rollback against an eventually-consistent broker.

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged). The staging reconcile suite now polls for BOTH eventually-consistent transitions it depends on: order appears/disappears on the book (`_poll_open_order`, case3) and a cancelled close reaches terminal (`_poll_closing_rollback`, case1). Production reconcile semantics are untouched.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/tests/staging/test_live_reconcile_staging.py` — `_poll_closing_rollback` helper; case1 rollback test polls instead of a single immediate reconcile.
- `projects/polymarket/crusaderbot/reports/forge/case1-test-poll.md` — this report.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — 7-section update.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry.

## 4. What is working

- `py_compile` clean. The helper reuses the existing `_factory` / `_settings_live` / `lr.reconcile_closing_positions` plumbing; the static `_Conn` fake makes re-runs re-query the broker.
- No production code touched; conservative `pending`-until-terminal behavior preserved.

## 5. Known issues

- Full pytest (pydantic + polymarket-client) not runnable in this container; validated via `py_compile` + logic review. Authoritative confirmation = CI (mocked) + the re-dispatched all-broker (real broker).

## 6. What is next

- all-broker re-dispatch (run-id tracked in the PR): expect TRUE 8/8. Acceptance: every `PROOF_RESULT` tied to the CURRENT machine id + run nonce (validates the harness fix end-to-end). Any failure surfaces DIAG to disambiguate harness-fix vs case1-poll source.
- After 8/8: only the owner-controlled LIVE flip remains.
