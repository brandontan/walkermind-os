# WARP•SENTINEL — Complete-Set Arb Lane 3B (LIVE two-leg FOK + auto-unwind)

**Branch:** `WARP/ROOT/complete-set-arb-lane3b-live-exec` (PR #1568)
**Validation Tier:** MAJOR (new LIVE execution / order path)
**Environment:** `dev` (infra + Telegram = warn-only; risk rules ENFORCED)
**Auditor:** WARP•R00T acting as WARP•SENTINEL (owner-authorised, per prior lanes)
**Source report:** reports/forge/complete-set-arb-lane3b-live-exec.md
**Reviewed commit:** `f8d25a6` (post Gemini + Codex P1 ×7 + P2 ×1 fixes)

---

## TEST PLAN

Phases 0–8 against `domain/execution/complete_set_exec.py` `book_complete_set_live`
(:387) and its helpers. Default assumption: UNSAFE until proven; code is truth,
every finding cites file:line. The lane is **UNWIRED** (no scan/registry caller)
and sits behind the 5 default-OFF activation guards + `USE_REAL_CLOB` +
`role=admin` + `trading_mode=live`, so runtime reachability is zero pending 3C.

---

## PHASE 0 — PRE-TEST (gate)

- Forge report at correct path + 6 sections + metadata → **PASS**.
- `state/PROJECT_STATE.md` updated (Lane 3B entry + 3C/SENTINEL handoff) → **PASS**.
- Zero `phase*/` folders; zero `phase*` imports (`find`/`grep`) → **PASS**.
- Hard-delete N/A (additive; no file moves; no migration — reuses mig 078 + 076).
- Critical-layer evidence: `book_complete_set_live` + helpers present, exercised.

Phase 0 → **CLEARED**.

---

## FINDINGS (per phase — evidence)

### Phase 1 — Functional
- Guards re-asserted first: `assert_live_guards` (:429) — `test_guard_failure_*`.
- Degenerate `shares<=0` short-circuits pre-IO (:422) — `test_non_positive_*`. PASS.

### Phase 2 — Pipeline
- **UNWIRED by design** (`grep` 0 callers; scan still skips a live decision at
  `complete_set_scan.py:237`). No runtime path → no bypass possible. PASS (dormant).

### Phase 3 — Failure modes (core)
FOK now resolves 3-way via `_fill_status` (:87) → filled / killed / **ambiguous**;
any non-terminal status (`delayed`, `live`, unknown) is ambiguous, never a clean
kill (Codex P1). Each submit site handles all three + the exception classes:
- YES killed → clean abort, NO never sent (:560-566). `test_yes_killed_*`.
- YES ambiguous (status OR exception) → halt + `LivePostSubmitError`, NO never sent
  (:567-588, :547). `test_yes_ambiguous_*`, `test_yes_delayed_status_*`.
- NO killed → YES naked → auto-unwind (:629-640). `test_no_killed_unwinds_*`.
- NO ambiguous (status OR exception) → persist CONFIRMED YES as tracked
  force-exitable + halt + raise; **no** auto-unwind (over-sell risk) (:606-654).
  `test_no_ambiguous_*`, `test_no_delayed_status_*`.
- Unwind pre-submit `ClobAuthError` → definitely naked → persist + halt (:797).
  `test_unwind_presubmit_clobauth_*`.
- Unwind ambiguous (status OR exception) → halt + raise, **no** re-sellable persist
  (may be flat → avoids double-close) (:808-855). `test_unwind_submit_ambiguous_*`,
  `test_unwind_delayed_status_*`.
- Unwind killed / no-bid-depth → naked_halt persist (:751, :856). `test_unwind_killed_*`,
  `test_unwind_no_bid_depth_*`.
- `_persist_naked_halt` DB failure → `naked_halt_persist_failed` + `persisted:false`
  + "UNTRACKED exposure" page (not swallowed; :921-980). `test_naked_persist_failure_*`.
- Both-fill persist failure → halt + `LivePostSubmitError` (no dupe). PASS.

### Phase 4 — Async safety
- Sequential FOK → no double-naked race; idempotency precheck (`= ANY(:yes,:no)`)
  + `ON CONFLICT DO NOTHING` claim + partial-claim rollback. `test_duplicate_*`. PASS.

### Phase 5 — Risk in code
- Arb invariant `yes_limit+no_limit >= COMPLETE_SET_PAYOUT` → reject (:504); limits ≥
  fill prices ⇒ conservatively guarantees `avg_pair_cost < $1`. `test_arb_invariant_*`.
- Cost integrity: legs recomputed from submit-time book (`_fill_plan`) so
  size_usdc/ledger/entry == actual spend (Codex P1). `test_persisted_cost_recomputed_*`.
- **Budget ceiling (Codex P1, resolved in-PR):** after the recompute, a combined
  cost exceeding the gate-approved `quote.total_cost_usdc` is rejected pre-submit —
  no LIVE overspend when books drift up (:~500). `test_submit_cost_over_approved_budget_rejects`.
- **Unwind proceeds (Codex P2, resolved in-PR):** unwind now credits the WEIGHTED
  bid proceeds (`_sell_plan`), not the bare limit — no wallet understatement.
  `test_unwind_credits_weighted_bid_proceeds`.
- Kill switch on every naked/ambiguous halt; 5 guards re-asserted (:429);
  LIVE guards never bypassed. PASS.
- **Halt is HARD (Codex P1, resolved in-PR):** `_halt_and_alert` retries
  `kill_switch.set_active`, and if it cannot engage it pages an URGENT "HALT DID NOT
  ENGAGE" alert and raises `LivePostSubmitError` — a failed halt is never swallowed
  (the gate halts only on the DB flag, so a swallowed failure would keep trading).
  `test_halt_killswitch_failure_raises_hard_not_swallowed`.
- Kelly/per-position + live-capital caps enforced UPSTREAM by the gate (Lane 2C);
  the budget ceiling above keeps the live spend inside that approved envelope.

### Phase 6 — Latency
- N/A. Sequential FOK trades one round-trip for deterministic naked handling —
  correct trade-off for a riskless arb. PASS.

### Phase 7 — Infra (dev warn-only)
- Hermetic tests (fake pool/clob/MDC); ledger verified via captured INSERT/UPDATE. PASS.

### Phase 8 — Telegram / operator
- `notify_operator` paged on every halt path; `notifications.send` on open/unwound
  (`_halt_and_alert`). PASS.

---

## CRITICAL ISSUES

**None found.** No runtime-reachable money/integrity defect: the path is UNWIRED and
behind 5 default-OFF guards, and every uncertain broker outcome (kill, ambiguous
status, ambiguous exception, DB-failure) routes to halt + operator reconciliation
rather than a silent guess.

## RESOLVED IN-PR (were flagged, now fixed on this branch)

- **H-1 (HIGH) — re-gate on recomputed cost → RESOLVED.** `book_complete_set_live`
  now rejects pre-submit when the recomputed combined cost exceeds the gate-approved
  `quote.total_cost_usdc`, so a book that drifts up cannot overspend the approved
  risk budget (Codex P1, commit `1441420`).
- **M-1 (MED) — unwind proceeds at limit → RESOLVED.** Unwind credits the weighted
  bid proceeds via `_sell_plan` (Codex P2, commit `1441420`).

## NON-BLOCKING FINDINGS (resolve in Lane 3C, before the path is reachable)

- **M-2 (MED, Codex P2) — reprice unwind from a fresh book.** The unwind sizes its
  SELL limit + proceeds from the `yes_book` captured at call time; if bids move
  during the YES/NO submits the credited proceeds is an estimate. A fresh fetch
  still races the fill — the authoritative fix is parsing the broker's actual fill,
  which is the same fill-reconciliation work as H-2. Deferred to Lane 3C with it.
- **H-2 (HIGH) — crash-recovery reconciliation.** A crash between a confirmed fill
  and the persist txn leaves 'pending'/'unknown' order rows; a retry hits the
  idempotency precheck and skips, so the on-chain fill is operator-reconciled via
  those rows (matches the existing `live.execute` posture). An automatic reconciler
  (and/or a `delayed`→terminal poll instead of halt) is out of scope here; Lane 3C
  should add it before the path goes live.

---

## STABILITY SCORE

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 19 | clean state machine; mirrors paper booker + live.execute patterns |
| Functional | 20 | 19 | 26 hermetic tests, every branch pinned |
| Failure modes | 20 | 20 | 3-way status + exception classes + persist-fail + hard-halt escalation |
| Risk rules | 20 | 20 | arb invariant + cost recompute + budget ceiling + guards (H-1 resolved) |
| Infra + Telegram | 10 | 9 | operator pages wired; infra N/A in dev |
| Latency | 10 | 10 | N/A; sequential-by-design correct |
| **Total** | **100** | **97** | zero critical |

No-evidence = 0 applied to none (all claims have file:line + a passing test).

---

## GO-LIVE STATUS

**VERDICT: APPROVED (97/100, 0 critical) — as of `f8d25a6`.**

Rationale: a MAJOR live-execution primitive whose every uncertain outcome halts and
reconciles instead of guessing; cost/accounting aligned to on-chain spend on both
legs and the unwind; an approved-budget ceiling that blocks LIVE overspend on book
drift; fully unit-tested; and runtime-unreachable (unwired + default-OFF guards) so
no defect can affect capital until Lane 3C. The sole remaining HIGH item (H-2,
crash reconciliation) is a MANDATORY Lane 3C pre-condition (3C is itself
MAJOR + SENTINEL), not a 3B blocker.

Conditions on merge (per CLAUDE.md, LIVE-touching):
1. Owner gives explicit merge nod.
2. Any further automated-review round on a newer commit is re-audited before merge.

---

## FIX RECOMMENDATIONS (priority)

1. (Lane 3C) Add crash-recovery reconciliation / `delayed`→terminal poll — H-2.
2. (Lane 3C) Re-run the FULL risk gate (live-capital cap, drawdown, concurrency) on
   the recomputed cost when wiring `chosen_mode=='live'` — the 3B budget ceiling
   covers the per-trade approved amount; the broader live caps belong to the gate.

## TELEGRAM PREVIEW (operator alerts emitted)

```
🛑 COMPLETE-SET NAKED LEG — TRADING HALTED
market=<id> side=yes cost=$45.00 reason=unwind_fok_killed
Naked leg persisted as <uuid> (force-exitable). Reconcile + resume manually.

🛑 ... ⚠️ PERSIST FAILED — naked leg NOT tracked. UNTRACKED live exposure — manual DB repair.

♻️ COMPLETE-SET NAKED LEG AUTO-UNWOUND  market=<id> side=yes realised=$-0.30 (spread). Trading continues.

🎯 [LIVE] Complete-set opened  shares=100 cost=$95.00 net_margin=$3.00
```

NEXT GATE: Return to WARP🔹CMD (owner) for the final LIVE-touching merge decision.
