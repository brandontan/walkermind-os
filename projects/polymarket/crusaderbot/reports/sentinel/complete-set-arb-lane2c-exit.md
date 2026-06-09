# WARP•SENTINEL — Complete-Set Arb Lane 2C-2a (exit-watcher hold rule)

**Branch:** `WARP/ROOT/complete-set-arb-lane2c-exit`
**PR:** #1563
**Validation Tier:** MAJOR (exit path — touches the close/settlement surface)
**Audit scope (owner-directed):** isolation of the `strategy_type == "complete_set_arb"`
bypass logic in the exit watcher; confirm standard directional trades still trigger
TP/SL without disruption.
**Default assumption:** UNSAFE until every check passes.

---

## TEST PLAN

- Phase 0 — Pre-test gate (report, state, structure, evidence)
- Phase 1 — Functional: bypass isolation in `evaluate()` + both `run_once()` expiry paths
- Phase 4 — Async safety of the new branches
- Phase 5 — Capital-integrity: no stake-refund leakage on a hedged set
- Regression — directional TP/SL/expiry paths unchanged

Environment: `dev` (code-truth audit; no infra dependency).

---

## PHASE 0 — PRE-TEST

- Forge report present, correct path + naming, all 6 sections + metadata — PASS
  (`reports/forge/complete-set-arb-lane2c-exit.md`)
- `state/PROJECT_STATE.md` + `CHANGELOG.md` updated — PASS
- No `phase*/` folders, domain structure intact — PASS
- Implementation evidence exists for the claimed surface — PASS

Phase 0: PASS — proceed to testing.

---

## FINDINGS (evidence = file:line)

### 1. `evaluate()` bypass isolation — PASS

`domain/execution/exit_watcher.py:422` — `if position.strategy_type == "complete_set_arb":
return ExitDecision(should_exit=False, ...)`.

- **Exact equality**, not membership/prefix — only the literal `complete_set_arb`
  is held; every other `strategy_type` (and `None`) falls through to the normal
  TP/SL/strategy/horizon logic. Zero blast radius on directional trades.
- **Ordering is correct.** `market_resolved` is handled first at line 400 (settles
  via redemption), and `force_close_intent` at line 410 (emergency unwind) — both
  BEFORE the skip at 422. So a set still settles on resolution and still obeys the
  operator kill path; it is held only against mid-trade TP/SL/horizon exits.

### 2. `run_once()` Phase A (None-price → MARKET_EXPIRED) — PASS

`exit_watcher.py:789-799`. Inside the `fail_count >= _EXPIRED_TICK_THRESHOLD`
block the first branch is `if p.strategy_type == "complete_set_arb"` (790): it
pins the counter to the threshold and falls through to the shared `continue` — it
never reaches `_close_expired_position`. The original expiry close is now an
`elif await _market_actually_expired(...)` (798), so directional behavior is
byte-for-byte unchanged. Counter is pinned (not popped/incremented), so the set
is re-checked each tick without unbounded growth — no leak, no busy-spin.

### 3. `run_once()` Phase B (resolved-market sweep) — PASS

`exit_watcher.py:840-849`. First statement in the loop body is the strategy guard
(842): a complete_set leg increments `held` and `continue`s; `_close_expired_position`
(849) runs only for non-set rows. Both legs of a resolved set are thus left for the
redemption pipeline (winning → $1, losing → $0).

### 4. Capital integrity — PASS (this is the core of the lane)

Both expiry paths terminate in `registry.close_as_expired(...)`, which **refunds
`size_usdc`**. For a hedged set that refund would return the stake instead of
letting the legs settle — silently inflating PnL and breaking the riskless-arb
invariant. Both paths now provably exclude `complete_set_arb`, closing the leak
Gemini flagged (resolved thread `r3340762496`).

### 5. Async safety — PASS

The new branches add no `await` on shared mutable state beyond the existing
`_price_fail_counts` dict write (single-task scheduler, same access pattern as the
surrounding code). No new locks, no new races, no state corruption. Per-position
exceptions remain isolated by the existing `try/except` in both loops.

### 6. Directional regression — PASS

All pre-existing directional tests pass unchanged: TP hit, SL hit, force-close
priority, horizon close, None-price-expiry (Phase A), resolved-market expiry
(Phase B). 56/56 in `tests/test_exit_watcher.py` (51 prior + 5 set-specific:
TP-hold, SL-hold, force-close-still-exits, Phase-A-no-expire, Phase-B-no-expire).
`assert_not_awaited()` on `close_as_expired` proves the no-refund guarantee.

---

## CRITICAL ISSUES

None found.

---

## STABILITY SCORE

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 20 | Skip placed after resolve + force-close; minimal, surgical |
| Functional | 20 | 20 | evaluate + both run_once paths verified |
| Failure modes | 20 | 19 | Pin-counter handles None-price storm; redemption-pipeline settlement is Lane 2C-2b (declared) |
| Risk/capital | 20 | 20 | Stake-refund leak closed on every expiry path |
| Infra+TG | 10 | 9 | No infra surface; N/A handled |
| Latency | 10 | 10 | Pure in-loop branch, no added I/O |
| **Total** | **100** | **98** | |

---

## GO-LIVE STATUS

**VERDICT: APPROVED** — Score 98/100, zero critical issues.

The `complete_set_arb` bypass is exactly-scoped (literal equality), correctly
ordered behind resolve + force-close, applied to all three exit surfaces
(`evaluate` + Phase A + Phase B), and proven non-refunding by test. Directional
trade behavior is unchanged. This is a defensive, inert-until-2C-2b hold rule and
is safe to merge.

Note: the lane remains PAPER-only and behind the default-OFF `COMPLETE_SET_ARB_ENABLED`
flag (wired in 2C-2b). LIVE is a separate owner-gated lane (Lane 3).

---

## FIX RECOMMENDATIONS

None required for merge.

- (2C-2b, tracked) Wire the redemption-pipeline settlement that actually realizes
  a held set's $1/$0 payoff; this PR only guarantees the watcher never wrongly
  refunds it.

---

## NEXT GATE

Return to WARP🔹CMD for the merge decision (owner merges; SENTINEL does not).
