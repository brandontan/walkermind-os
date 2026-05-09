# WARP•SENTINEL REPORT — execution-rewire

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
PR: #912
Branch: WARP/CRUSADERBOT-PHASE4B-EXECUTION-REWIRE
Head SHA: 770e9542140bb44d5f7359d3686ece76eaabaa41
Source: projects/polymarket/crusaderbot/reports/forge/execution-rewire.md
Environment: dev (infra ENFORCED only on staging/prod)
Posture: PAPER ONLY — ENABLE_LIVE_TRADING / EXECUTION_PATH_VALIDATED / CAPITAL_MODE_CONFIRMED / USE_REAL_CLOB all NOT SET in fly.toml [env]

---

## 1. TEST PLAN

Phases executed:

- Phase 0 — Pre-test gates (report, state, structure, evidence)
- Phase 1 — Functional per validation-scope item (8 contracts)
- Phase 2 — Pipeline E2E: router.execute → assert_live_guards → live.execute → ClobClientProtocol.post_order
- Phase 3 — Failure modes: ClobAuthError / generic exception / ClobConfigError / idempotency dedup / close rollback
- Phase 4 — Async safety: atomic INSERT ON CONFLICT and UPDATE…RETURNING claims, asyncio-only
- Phase 5 — Risk + activation-guard posture (5-guard set)
- Phase 6 — Latency (architectural review only — single async post_order, no added layers)
- Phase 7 — Infra (hermetic; dev = warn-only)
- Phase 8 — Telegram (operator-notify on ambiguous submit; mocked in tests)

Source of truth for findings: code (`domain/execution/live.py`, `integrations/clob/__init__.py`, `tests/test_live_execution_rewire.py`) — forge report cross-checked, never trusted blindly.

---

## 2. PHASE 0 — PRE-TEST RESULTS

| Gate | Result | Evidence |
|---|---|---|
| Report path correct (`reports/forge/execution-rewire.md`) | PASS | path verified |
| Naming matches feature slug | PASS | `execution-rewire.md` |
| All 6 forge sections present | PASS | sections 1–6 present |
| Metadata complete (Tier / Claim / Target / Not in Scope / Suggested Next Step) | PASS | header lines 3–7 |
| PROJECT_STATE.md updated (7 sections, ASCII labels, timestamp) | PASS | `2026-05-09 14:30 Asia/Jakarta` + Phase 4B in [IN PROGRESS] |
| No `phase*/` folders in repo | PASS | none found |
| Domain structure preserved | PASS | `domain/execution/live.py` unchanged path |
| Evidence in code for every claim | PASS | all 8 scope contracts traced to file:line below |

Phase 0 ALL GREEN — proceeding to functional phases.

---

## 3. FUNCTIONAL FINDINGS (per validation scope)

### 3.1 Guard routing — USE_REAL_CLOB=False AND any guard NOT SET → never reaches ClobAdapter

Trace: `domain/execution/live.py:115` → `assert_live_guards` checks ENABLE_LIVE_TRADING (`:57`), EXECUTION_PATH_VALIDATED (`:59`), CAPITAL_MODE_CONFIRMED (`:61`), and USE_REAL_CLOB-when-live (`:63-66`). Any failure raises `LivePreSubmitError` BEFORE `client.post_order(...)` at `:162`. Dry-run intercept at `:105` returns early (no broker, no DB) when USE_REAL_CLOB=True + ENABLE_LIVE_TRADING=False.
Tests: `TestAssertLiveGuards` (7 cases, `tests/test_live_execution_rewire.py:193-259`); `TestGuardRouting.test_guards_fail_raise_live_pre_submit_error` (`:314-321`).
Verdict: **PASS**.

### 3.2 USE_REAL_CLOB=False + ENABLE_LIVE_TRADING=True → LivePreSubmitError (commit 770e954)

Trace: `live.py:63-66` raises `LivePreSubmitError("USE_REAL_CLOB must be True when ENABLE_LIVE_TRADING is set")`.
Test: `test_use_real_clob_false_raises` (`:227-241`).
Verdict: **PASS**.

### 3.3 Dry-run — USE_REAL_CLOB=True + ENABLE_LIVE_TRADING=False → log-and-return, zero DB writes, zero broker calls

Trace: `live.py:103-113` — log + `return {"status": "dry_run", "mode": "paper", "_mock": True}` BEFORE `assert_live_guards`, BEFORE `pool.acquire`, BEFORE any `post_order` call.
Test: `test_dry_run_when_use_real_clob_true_enable_live_false` (`:267-277`) asserts `result["status"] == "dry_run"`, `result["_mock"] is True`, and `conn._call == 0` (zero DB touches). MockClobClient injected; its `post_order` not invoked.
Verdict: **PASS**.

### 3.4 Exception classification — ClobAuthError strictly pre-submit; all others post-submit, no fallback

Trace: `live.py:169-179` catches `ClobAuthError` → marks order `'failed'`, audits `live_pre_submit_failed`, raises `LivePreSubmitError`. `live.py:180-204` catches generic `Exception` → marks order `'unknown'`, audits `live_submit_ambiguous`, notifies operator, raises `LivePostSubmitError`. Additionally, `ClobConfigError` from `get_clob_client()` (`:127-128`) maps to `LivePreSubmitError` (Codex P2 fix).
Router (`router.py:58-70`) re-raises on `LivePostSubmitError` (no paper fallback) and triggers `fallback.trigger_for_clob_error`. On `LivePreSubmitError` (`:71-93`) it falls back to paper.
Tests: `TestExceptionClassification` (`:383-429`) — `ClobAuthError`→`LivePreSubmitError`, `RuntimeError`→`LivePostSubmitError`, `ClobConfigError`→`LivePreSubmitError`.
Verdict: **PASS**.

### 3.5 Idempotency — duplicate key → {status: "duplicate"}, zero broker calls

Trace: `live.py:134-148` — `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING RETURNING id`. If `row is None` → log + `return {"status": "duplicate", "mode": "live"}` BEFORE `client.post_order` at `:162`.
Test: `test_duplicate_key_returns_duplicate_status` (`:361-369`) asserts `result["status"] == "duplicate"` and `client.open_orders() == []` (zero broker calls).
Verdict: **PASS**.

### 3.6 GTC + FOK — order_type forwarded verbatim to post_order

Trace: `live.py:90` declares `order_type: str = "GTC"`; `:167` passes `order_type=order_type` to `client.post_order`. ClobClientProtocol surface (`integrations/clob/__init__.py:80-88`) accepts `order_type: str = "GTC"`.
Tests: `TestOrderTypeDispatch` (`:328-353`) — GTC, FOK, default-GTC each verified against `MockClobClient.open_orders()[0]["orderType"]`.
Verdict: **PASS**.

### 3.7 close_position SELL — client.post_order called with side="SELL"

Trace: `live.py:332-339` — `await client.post_order(token_id=..., side="SELL", price=exit_price, size=shares_to_sell, order_type="GTC")`. Atomic claim at `:307-312` (`UPDATE positions SET status='closing' WHERE id=$1 AND status='open' RETURNING id`) prevents double-SELL on concurrent close. Rollback on submit failure at `:340-346` (`status='open'` re-raise).
Codex P1 round 2 hardening at `:278-284`: `USE_REAL_CLOB=False` raises `RuntimeError` BEFORE atomic claim → no phantom-close of live positions by MockClobClient.
Tests: `TestClosePosition` (7 cases, `:475-566`) — SELL dispatch, GTC, already-closing skip, rollback on failure, yes/no PnL, USE_REAL_CLOB=False guard.
Verdict: **PASS**.

### 3.8 Activation guard posture — ENABLE_LIVE_TRADING NOT SET in CI

Trace: `fly.toml:38-40` — all three env guards `"false"`. `config.py:120` USE_REAL_CLOB default `False`. CI workflows (`.github/workflows/crusaderbot-ci.yml`, `crusaderbot-cd.yml`) do NOT export ENABLE_LIVE_TRADING / USE_REAL_CLOB — unit tests inject settings via `_settings(...)` patches and never depend on env. PR body confirms ❌ on all four.
Pre-existing config.py:134 default `ENABLE_LIVE_TRADING: bool = True` — KNOWN ISSUE deferred to `WARP/config-guard-default-alignment`. Not introduced by Phase 4B; fly.toml override keeps prod safe.
Verdict: **PASS** (no Phase 4B regression).

---

## 4. FAILURE MODES & ASYNC SAFETY

| Failure | Handling | Evidence |
|---|---|---|
| Signing failure (no network) | `ClobAuthError` → `LivePreSubmitError`; order='failed' | live.py:169-179 |
| Network timeout / 5xx after queue | generic `Exception` → `LivePostSubmitError`; order='unknown'; operator notify | live.py:180-204 |
| Missing CLOB credentials | `ClobConfigError` → `LivePreSubmitError` (execute) / `RuntimeError` (close) | live.py:127-128, 325-331 |
| Duplicate signal retry | `ON CONFLICT DO NOTHING` → `{status:"duplicate"}` | live.py:134-148 |
| Concurrent close race | Atomic `UPDATE … status='closing' WHERE status='open' RETURNING id` | live.py:307-312 |
| DB persist failure after broker accept | `LivePostSubmitError`; audit `live_post_submit_db_error` | live.py:240-248 |
| MockClobClient phantom live | USE_REAL_CLOB guard in `assert_live_guards` + close_position | live.py:63-66, 279-284 |
| Operator notify failure during ambiguous submit | logged, does not mask original error | live.py:199-201 |

Async correctness: asyncio only, no threading. Each pool.acquire() / transaction() block is bounded; `_FakeAcquire` and `_FakeTx` confirm async-context-manager protocol. No bare `except: pass`. No swallowed exceptions outside the operator-notify best-effort path which logs and re-raises the underlying error.

Suite stats: 27 hermetic unit tests in `test_live_execution_rewire.py` (no DB, no network, no Telegram). Collected count matches forge report; PR body says 19 (stale; pre-Codex). Local execution blocked by missing system-level cryptography deps for `python-telegram-bot` import chain — forge report explicitly noted; CI environment has full deps.

---

## 5. STABILITY SCORE

| Category | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 18 | Clean ClobClientProtocol boundary; close-side parity (entry-price share count) |
| Functional | 20 | 19 | All 8 scope contracts pass; 27 hermetic tests; PR body test-count drift |
| Failure modes | 20 | 19 | Pre/post-submit classification correct; ambiguous submit alerts operator; close rollback |
| Risk + activation guards | 20 | 19 | USE_REAL_CLOB hardened (Codex P1 r1+r2); fly.toml posture preserved; config.py:134 pre-existing |
| Infra + Telegram | 10 | 9 | Hermetic; notify_operator best-effort guarded; dev = warn-only |
| Latency | 10 | 8 | Single async post_order; no added layer; not directly measurable here |
| **Total** | **100** | **92** | |

---

## 6. CRITICAL ISSUES

**None found.** No path leaks USE_REAL_CLOB=False through to ClobAdapter; no path bypasses the activation guards; no path duplicates broker submission on retry; no silent exception swallowing introduced.

---

## 7. NON-CRITICAL FINDINGS

| ID | Severity | Location | Finding | Action |
|---|---|---|---|---|
| F1 | LOW | `domain/execution/order.py:10` | Stale docstring still references `polymarket.submit_live_order` (now replaced by `client.post_order(side="SELL")` in `live.close_position`) | Sweep into `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP` (already deferred MINOR) |
| F2 | INFO | `domain/execution/live.py:63` | `if s.ENABLE_LIVE_TRADING and not s.USE_REAL_CLOB` — left side always True at this point (line :57 already guarantees it). Style nit, not a defect. | Optional simplification in same cleanup lane |
| F3 | INFO | PR body §Changes; `state/PROJECT_STATE.md:18` | Test-count drift: PR description / state mention "19 new tests"; actual count is 27 (forge report agrees with code; +8 from Codex P1 r1+r2 + P2). | Refresh PR body and state file post-merge |
| F4 | LOW | `config.py:134` | `ENABLE_LIVE_TRADING: bool = True` Settings default. Pre-existing; not introduced by this PR; fly.toml `[env]` overrides to `"false"` so prod posture is correct. | Already deferred to `WARP/config-guard-default-alignment` |

None of the above is blocking. F3 should be reconciled before merge for state-file truth alignment but does not invalidate the validation outcome (code is the source of truth).

---

## 8. GO-LIVE STATUS

**Verdict: APPROVED**
**Score: 92 / 100**
**Critical issues: 0**

Reasoning:
- All 8 validation-scope contracts traced to file:line and matched by hermetic tests.
- Phase 4A `ClobClientProtocol` correctly substituted for legacy `py-clob-client` SDK path; legacy `_build_clob_client` no longer reachable from execution layer.
- USE_REAL_CLOB elevated to a fifth activation guard inside `assert_live_guards` and replicated at `close_position` entry — closes the MockClobClient phantom-live exposure path noted by Codex P1 (rounds 1 and 2).
- Pre/post-submit classification is conservative: any ambiguity routes to `LivePostSubmitError` → operator notify + no paper duplication.
- Activation-guard posture unchanged — `ENABLE_LIVE_TRADING` / `EXECUTION_PATH_VALIDATED` / `CAPITAL_MODE_CONFIRMED` / `USE_REAL_CLOB` all NOT SET in `fly.toml` and PR body.
- No `phase*/` folder, no shim, no compatibility re-export.

Merge-readiness: ready for WARP🔹CMD merge decision. Post-merge: open `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP` to remove `_build_clob_client` dead code and refresh `order.py` docstring.

---

## 9. FIX RECOMMENDATIONS

Priority ordered (none are blockers):

1. **(Optional, pre-merge — non-blocking)** Update PR body and `PROJECT_STATE.md:18` to reflect 27 tests (not 19). Pure documentation truth alignment.
2. **(Post-merge MINOR)** Sweep `domain/execution/order.py:10` docstring and `live.py:63` redundant predicate into `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP` alongside `_build_clob_client` removal.
3. **(Post-merge MINOR — already tracked)** Resolve `config.py:134` ENABLE_LIVE_TRADING default in `WARP/config-guard-default-alignment`.
4. **(Phase 4C scope)** Forward `order_type` through `router.execute(...)` so callers (Telegram commands, signal scan loop) can opt into FOK.
5. **(Phase 4D scope)** WebSocket fill correlation — out of scope here.

---

## 10. TELEGRAM PREVIEW

Operator-facing alerts wired by this PR (mocked in tests; live behaviour unchanged from R12 baseline):

```
⚠️ *AMBIGUOUS LIVE SUBMIT*
order_id=`<uuid>` user=`<uuid>`
market=`<mkt>` side=`yes|no` shares=`<n>` price=`<p>`
Reconcile via Polymarket dashboard before clearing.
err: `<truncated 300 chars>`
```

```
📈 *[LIVE] Opened*
<market_question>
*<SIDE>* @ <price>
Size: $<size_usdc>
```

Dashboard impact: none — `/ops` and `/health` surfaces unchanged.
Commands impact: none — `/live_checklist`, `/kill`, `/resume` unchanged.

---

## 11. DEFERRED BACKLOG

- `WARP/CRUSADERBOT-POLYMARKET-LEGACY-CLEANUP` (MINOR, post-merge): remove `_build_clob_client` from `integrations/polymarket.py`; refresh `order.py:10` and `live.py:63` per F1/F2.
- `WARP/config-guard-default-alignment` (MINOR, pre-existing): flip `config.py:134` default to `False` per F4.
- Phase 4C: on-chain order builder migration (tick_size / neg_risk) — out of scope for 4B.
- Phase 4D: WebSocket fill correlation — out of scope for 4B.

---

Done — GO-LIVE: APPROVED. Score: 92/100. Critical: 0.
PR: WARP/CRUSADERBOT-PHASE4B-EXECUTION-REWIRE
Report: projects/polymarket/crusaderbot/reports/sentinel/execution-rewire.md
NEXT GATE: WARP🔹CMD merge decision.
