# WARP-90 — Server-side TP/SL bounds + NULL fallback for fast_topup / safe_close

Branch: `WARP/1688-tpsl-server-bounds`
Role: WARP•FORGE
Validation Tier: **MAJOR**
Claim Level: **NARROW INTEGRATION**
Validation Target: the two CONDITIONAL-PASS conditions from
`projects/polymarket/crusaderbot/docs/sentinel/1688_retroactive_sentinel.md`
(§3 + §5) — (A) server-side numeric bounds on user-supplied TP/SL, and (B) the
NULL→strategy-default fallback on the `fast_topup` and `safe_close` builder paths.
Not in Scope: changing the EV-validated 1.5/0.5 strategy defaults; any DB
migration / schema change; `domain/risk/gate.py` or `domain/risk/slippage_gate.py`
(other lane); `ENABLE_LIVE_TRADING` / `SCORER_ACTIVE` / `ORCHESTRATOR_ACTIVE`;
frontend.

---

## 1. What was built

Two fixes closing the open items from the PR #1688 retroactive SENTINEL
(CONDITIONAL PASS):

**(A) Server-side TP/SL validation (the authoritative guard).**
The SENTINEL finding was that user-supplied `tp_pct` / `sl_pct` reach the
`user_settings` row and are consumed raw at execution time with no server-side
numeric clamp — `sl_pct = 0` (no stop-loss), a negative value, or an absurd
`tp_pct` were all accepted. The custom-risk-profile override write path
(`set_risk_profile`, `webtrader/backend/router.py`) enforced only ordering
(`tp > sl`) and "at least one set" — no bounds. (The sibling `customize_strategy`
endpoint already had inline bounds, but `set_risk_profile` did not, and inline
guards do not protect every future write path.)

Fix: bounds are now enforced at the **Pydantic schema layer** — the one place
every write path funnels through. New reusable validators in
`webtrader/backend/schemas.py`:

- `MIN_SL_PCT = 0.01` (messaging floor), `MAX_SL_PCT = 1.0`, `MAX_TP_PCT = 10.0`.
- `_validate_sl_pct`: rejects a present `sl_pct <= 0` or `> 1.0`.
- `_validate_tp_pct`: rejects a present `tp_pct <= 0` or `> 10.0`.
- `None` is always allowed (means "use the strategy default").

Wired as `field_validator` on the three write schemas that accept these fields:
`CustomizeRequest`, `RiskProfileRequest`, `AdminUserUpdate`. An out-of-range
present value now raises `ValidationError` → FastAPI **422** before the handler
runs, so it cannot be bypassed via any endpoint (including the previously-unguarded
`set_risk_profile`).

**(B) NULL→strategy-default fallback on the two secondary builder paths.**
PR #1688 (and WARP-85) gave the normal-mode builder
(`_build_trade_signal`) a logged NULL→`_strategy_default_tp_sl()` fallback. The
SENTINEL noted the secondary builders still passed `None` on a NULL row. Both now
mirror the normal-mode mechanism exactly, in
`services/signal_scan/signal_scan_job.py`:

- `_maybe_fire_fast_topup`: resolves NULL `tp/sl` via
  `_strategy_default_tp_sl(_LATE_ENTRY_V3_NAME)` (fast_topup is scoped to
  `safe_close`/`flip_hunter` → `late_entry_v3`), logs
  `user_settings_{tp,sl}_pct_missing_defensive_fallback` with `mode="fast_topup"`.
- The stale-queue **resume** path (covers `safe_close`): resolves via
  `_strategy_default_tp_sl(_STRATEGY_NAME)` (the strategy_type the resume actually
  executes — `signal_following`), logs the same markers with
  `mode="safe_close_resume"`.

A NULL `user_settings` row can no longer emit a position with `tp/sl = None` on
any builder path.

---

## 2. Current system architecture

Unchanged pipeline (`DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION →
MONITORING`). TP/SL remains STRATEGY-stage-owned (exit thresholds resolve from the
active strategy's `default_tp_sl()` hook when the user value is NULL); the risk
profile still governs capital sizing only. This lane adds:

- An input-validation boundary at the API edge (Pydantic schema layer) for the
  one user-controllable exit-threshold input. Invalid → 422, no DB write, no
  handler execution.
- Defensive NULL-fallback parity across all three signal builders (normal,
  fast_topup, safe_close-resume), so the "never emit `None` TP/SL" invariant holds
  everywhere, not just normal mode.

No new dependency, no migration, no flag, no risk-constant change.

---

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` — TP/SL bound
  constants + `_validate_tp_pct` / `_validate_sl_pct`; `field_validator` hooks on
  `CustomizeRequest`, `RiskProfileRequest`, `AdminUserUpdate`.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` —
  NULL→strategy-default fallback in `_maybe_fire_fast_topup` and the stale-queue
  `safe_close` resume path (replacing the bare `else None` passthroughs).
- `projects/polymarket/crusaderbot/tests/test_admin_console.py` — the `tp_pct` /
  `sl_pct` out-of-range cases in `test_admin_user_update_validates_numeric_bounds`
  moved to a new `test_admin_user_update_tpsl_rejected_at_schema_layer` (they now
  reject at construction with `ValidationError` → 422 instead of the router-layer
  400; the other params still test the router 400 path).

Created:
- `projects/polymarket/crusaderbot/tests/test_tpsl_server_bounds.py` — per-invalid-input
  rejection tests (A) + per-path NULL-fallback tests (B).

---

## 4. What is working

- Schema validators reject `sl_pct=0`, `sl_pct=-0.1`, `sl_pct=2.0`, `tp_pct=0`,
  `tp_pct=999` (verified on all three write schemas); `None` and in-range values
  (incl. boundary `tp=10.0` / `sl=1.0` and the 1.5/0.5 default) pass.
- `RiskProfileRequest(profile="custom", sl_pct=0)` / `tp_pct=999` now raise
  `ValidationError` (the previously-unguarded override path).
- fast_topup with NULL `tp_pct` falls back to `default[0]` (1.5) and honours a
  present `sl_pct` literally; NULL-both → full (1.5, 0.5) default pair; a present
  value passes through untouched.
- safe_close resume path resolves NULL `sl_pct` to `default[1]` (0.5) via the
  shared resolver (pinned at source + via `_strategy_default_tp_sl`).
- `pytest projects/polymarket/crusaderbot/tests/ -q`: **3099 passed, 15 skipped**.
  The only failures are 4 pre-existing `test_clob_pysdk` tests that fail
  identically on clean `origin/main` (sandbox `py-clob-client` version skew —
  unrelated to this lane).
- `ruff check .`: **All checks passed.**

---

## 5. Known issues

- The stale-queue `safe_close` **resume** block is buried inside the scan-job
  entry coroutine and is not independently callable, so its NULL-fallback is
  pinned by a source-contract test + the shared `_strategy_default_tp_sl`
  resolver rather than a full end-to-end DB-driven run. The runtime behaviour is
  identical to the (behaviourally tested) fast_topup + normal-mode paths since all
  three share the same resolver.
- Sandbox could not run the suite without manually installing absent runtime deps
  (`cffi`/cryptography backend, `tenacity`, `structlog`, `sse_starlette`,
  `bcrypt`, `apscheduler`, `pytest-asyncio`, etc.). These are environment gaps,
  not code issues (same condition the #1688 SENTINEL documented). CI on the PR is
  the test gate of record.

---

## 6. What is next

- WARP•SENTINEL validation (MAJOR) before merge.
- (Outside this lane) The excursion-capture / per-position MFE-MAE instrumentation
  lane (KNOWN ISSUES in PROJECT_STATE) remains the prerequisite for any future
  TP/SL cutover away from 1.5/0.5.

Suggested Next Step: WARP•SENTINEL run on `WARP/1688-tpsl-server-bounds`
(Source: this report), then WARP🔹CMD merge decision.
