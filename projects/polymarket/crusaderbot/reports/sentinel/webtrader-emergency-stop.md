# WARP•SENTINEL REPORT — webtrader-emergency-stop (validated by WARP•R00T)

## TEST PLAN

Environment: dev (code-truth audit; live Fly verification deferred to post-deploy)
Scope: PR #1357 — `POST /api/web/emergency-stop` + DesktopSidebar trigger.
Posture: close-all path treated as UNSAFE until the force-close → actual-close chain is proven in code.

## FINDINGS

### Phase 0 — Pre-Test
- Forge report present, correct path, 6 sections + metadata — PASS (reports/forge/webtrader-emergency-stop.md)
- PROJECT_STATE + CHANGELOG updated — PASS
- No `phase*/` folders, domain structure intact — PASS

### Phase 1 — Functional (the critical chain)
- `evaluate()` exit_watcher.py:322 — `force_close_intent` is the **highest-priority** branch, returns `ExitReason.FORCE_CLOSE`; wins even over a breached TP/SL (proven by tests `test_evaluate_force_close_intent_overrides_tp/_sl`). PASS — marking a position guarantees it closes next tick.
- Exit price: with `live_price=None` (force-close skips the Gamma fetch, run_once:623-625), `evaluate` uses `position.current_price()` — the last mark-to-market price refreshed every watcher tick. Satisfies "close at market price, profit or loss". PASS.
- `mark_force_close_intent_for_user` (registry.py:306) — `UPDATE positions SET force_close_intent=TRUE WHERE user_id=$1 AND status='open' AND force_close_intent=FALSE`; returns rows flipped. Scoped to the user. PASS.
- `kill_switch.set_active(action="pause", actor_id=None, reason=…)` — signature matches (kill_switch.py:188); `"pause"` ∈ _VALID_ACTIONS. PASS.

### Phase 3 — Failure modes
- No open positions → mark returns 0, endpoint returns `{positions_marked:0, kill_switch_active:true}` — no error. PASS.
- Double-submit → mark is idempotent (`force_close_intent=FALSE` guard); re-pausing kill switch is harmless. PASS.
- Exception path → caught, logged, HTTP 500. PASS.
- Partial state (kill set, mark raises) → fail-safe: trading is halted; user can retry the close. Acceptable — errs on the safe side. PASS.

### Phase 4 — Async safety
- asyncio only; no threading; no shared mutable state; pool.acquire scoped per call; kill switch flips inside its own transaction. PASS.

### Phase 5 — Risk rules
- No RISK-gate bypass — close path does not touch the entry gate; kill switch blocks new entries. PASS.
- `ENABLE_LIVE_TRADING` untouched; kill action validated against allowed set. PASS.
- User isolation — force-close UPDATE scoped `WHERE user_id=$1`. PASS.

### Phase 7 — Infra / observability
- `audit.write(action="webtrader_emergency_stop_close_all", payload={positions_marked})`. PASS.
- Runtime import of `crusaderbot.webtrader.backend.router` OK; `/emergency-stop` route registered. PASS.

### Regression
- tests/test_exit_watcher.py — 38 passed.
- position/kill/force_close/registry/emergency selection — 195 passed, 0 failures.
- Frontend: all identifiers referenced (no TS6133); tsc gated by CI/Docker (not run in this env).

## CRITICAL ISSUES
None found.

## STABILITY SCORE
- Architecture 20/20 — reuses proven kill-switch + force-close primitives; no new close logic.
- Functional 20/20 — force-close → close chain verified end-to-end in code + tests.
- Failure modes 20/20 — idempotent, fail-safe, empty-set safe.
- Risk 20/20 — no guard bypass, user-scoped, action validated.
- Infra + observability 9/10 — audited + imports clean; no dedicated endpoint-level test (primitives are tested).
- Latency 5/5 / Frontend 5/5 — force-close skips price fetch (faster unwind); frontend tsc deferred to CI.
TOTAL: 94/100.

## GO-LIVE STATUS
APPROVED (score 94 ≥ 85, zero critical issues). Safe to merge.

## FIX RECOMMENDATIONS
- P3 (non-blocking): add a hermetic test for the endpoint composition (mock kill_switch + mark fn).
- Decision (WARP🔹CMD): global kill switch vs per-user pause for the multi-user public phase — current global behavior matches existing `/kill`, correct for single-owner paper.

## POST-DEPLOY VERIFICATION (after Fly deploy)
- Open ≥2 positions (one in profit, one in loss) → Stop All → both close within one watcher tick; dashboard shows kill-switch banner; new trades blocked; one `webtrader_emergency_stop_close_all` audit row.
