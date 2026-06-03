# WARP•SENTINEL — complete-set-arb-lane3c-reconcile

Validator: WARP•R00T acting as WARP•SENTINEL (owner-authorised).
Branch: `WARP/ROOT/complete-set-arb-lane3c-reconcile`
**Reviewed commit:** `84cf5c0`.
Tier: MAJOR (LIVE order reconciliation / money-state correctness).
Environment: `dev` (Risk ENFORCED). Default posture: UNSAFE until proven. Code is truth.

---

## TEST PLAN

Scope = the three Lane 3C-2 deliverables: exact-fill booking, `delayed`→terminal
poll, the set-aware crash-recovery reconciler + the directional-poller exclusion.
Phases: 0 (pre-test), 1 (functional), 3 (failure modes), 4 (async safety), 5 (risk),
+ reconciler routing + reachability/dormancy.

## FINDINGS (evidence — file:line)

**Phase 0 (PASS):** forge report at correct path + 6 sections + metadata;
no `phase*/` folders; no migration needed (reuses mig 026/078); implementation read
directly. PASS.

**Phase 1 — Functional (PASS):**
- Exact fill: `_exact_fill_cost` (`complete_set_exec.py`) books `get_fills` actuals
  at the both-fill persist, naked cost, and unwind proceeds; falls back to the
  estimate on absent/incomplete fills. 4 tests incl. parser-unit. PASS.
- Delayed poll: `_poll_terminal_status` re-resolves AMBIGUOUS at the 3 sites; the
  fill var is re-assigned so existing terminal branches handle it. 4 tests. PASS.
- Reconciler: `reconcile_complete_set_orders` SELECT (pending/unknown + no position +
  age) → `_reconcile_one_order` routes not-filled→cancel / filled→naked-halt /
  unverifiable+ambiguous→halt. 7 tests. PASS.

**Phase 3 — Failure modes (PASS):**
- `get_fills`/`get_order` query failure → estimate kept / ambiguous (caller halts) —
  never a false terminal, never blocks the persist (`_exact_fill_cost`,
  `_poll_terminal_status`). PASS.
- Reconciler: per-order errors isolated (`out["errors"]`), client always closed
  (`finally`), scan failure returns instead of raising (scheduler-safe). PASS.
- Halt-on-uncertainty: no broker id / ambiguous / query-fail all → `_halt_and_alert`
  + page, order untouched (`test_no_broker_id_halts_unverifiable`,
  `test_still_ambiguous_halts`). PASS.

**Phase 4 — Async safety (PASS):** no shared mutable state; reconciler per-row;
poll uses `asyncio.sleep` only between attempts; no threading. PASS.

**Phase 5 — Risk-rule preservation (PASS / IMPROVED):**
- **Directional poller now EXCLUDES complete-set legs** (`lifecycle.py:117` SQL
  `NOT LIKE 'complete_set_arb%'`), closing a real hazard — its refund-on-cancel
  logic would have broken a hedge if it caught a set leg in its transient `pending`
  window. 57 directional lifecycle tests still pass. PASS.
- Exact-fill closes the overspend-understatement (Codex P1) — ledger now reflects
  actual spend. Reconciler reuses the kill switch on every uncertainty. PASS.
- Reconciler NEVER refunds, NEVER silently deletes — confirmed by routing tests.

**Reachability / dormancy (PASS):** exact-fill + poll live inside
`book_complete_set_live` (already behind the 5 guards + `COMPLETE_SET_ARB_ENABLED`).
The reconciler job is registered ONLY when `COMPLETE_SET_ARB_ENABLED` and no-ops
unless `USE_REAL_CLOB` (`test_noop_in_paper_mode`). Zero runtime reach today.

## CRITICAL ISSUES

**None reachable.** The Codex P1 (stale-book overspend) and SENTINEL H-2/M-2 that
were the documented pre-LIVE blockers are now CLOSED by this lane. The NULL-broker-id
crash case is handled conservatively (halt + page), not a gap.

## STABILITY SCORE

| Dimension | Weight | Score | Evidence |
| --- | --- | --- | --- |
| Architecture | 20 | 19 | DRY reuse; set-aware reconciler; directional exclusion; 4 config knobs |
| Functional | 20 | 19 | exact-fill / poll / reconciler all pinned (15 new tests) |
| Failure modes | 20 | 19 | query-fail safe; per-order isolation; halt-on-uncertainty |
| Risk rules | 20 | 19 | hedge-safe exclusion; overspend closed; never-refund |
| Infra + TG | 10 | 10 | scheduler-wired (gated); operator pages on every halt |
| Latency | 10 | 10 | exact-fill after-terminal (no YES→NO cost); poll only on rare delayed |
| **Total** | **100** | **96** | **zero reachable critical** |

## GO-LIVE STATUS

**VERDICT: APPROVED (96/100, 0 reachable critical) — as of `84cf5c0`.**
Safe to MERGE. With this lane the complete-set LIVE path has its full pre-flip safety
net (exact accounting + delayed resilience + crash reconciliation + hedge-safe
poller). The LIVE flip (operator sets the 5 guards + `COMPLETE_SET_ARB_ENABLED`)
remains an owner-gated operational decision — an optional small live-fire validation
is the natural final step before scaling capital.

## FIX RECOMMENDATIONS

1. None blocking. (Optional, future) persist broker ids mid-flight to let the
   reconciler auto-resolve NULL-broker-id crash leftovers instead of halting — only
   if the hot-path latency cost is acceptable; not required for safety.

## TELEGRAM PREVIEW

New operator pages on reconcile: `🛑 COMPLETE-SET NAKED LEG — TRADING HALTED`
(untracked-fill persisted) and the unverifiable/ambiguous halt alerts. Structured
logs: `complete_set_reconcile_sweep`, `complete_set_exact_fill`,
`complete_set_delayed_poll_resolved`.

---

Done -- GO-LIVE: APPROVED. Score: 96/100. Critical: 0 reachable.
PR: WARP/ROOT/complete-set-arb-lane3c-reconcile
Report: projects/polymarket/crusaderbot/reports/sentinel/complete-set-arb-lane3c-reconcile.md
State: PROJECT_STATE.md updated
NEXT GATE: WARP🔹CMD merge decision; LIVE flip owner-gated (optional live-fire first).
