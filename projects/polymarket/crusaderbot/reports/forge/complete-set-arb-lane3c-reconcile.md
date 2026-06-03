# WARP•FORGE — complete-set-arb-lane3c-reconcile

Branch: `WARP/ROOT/complete-set-arb-lane3c-reconcile`
Role: WARP•FORGE (WARP•R00T)
Validation Tier: **MAJOR** (LIVE order reconciliation / money-state correctness)
Claim Level: **NARROW INTEGRATION**
Validation Target: exact-fill cost/proceeds booking, `delayed`→terminal poll, the
set-aware crash-recovery reconciler routing, and the directional-poller exclusion.
Not in Scope: LIVE live-fire validation (real capital); redemption/settlement;
the scan→live wiring (Lane 3C-1, merged).
Suggested Next Step: WARP•SENTINEL validation → owner review/merge. After merge the
complete-set LIVE path has its full pre-flip safety net; the LIVE flip itself stays
owner-gated.

---

## 1. What was built

Lane 3C-2 — the reconciliation pre-conditions the prior SENTINEL ruled MANDATORY
before the complete-set LIVE path may be flipped on (H-2 + M-2 + the Codex P1
stale-book overspend). Three pieces, built + tested as chunks:

1. **Exact-fill reconciliation (chunk 1)** — `book_complete_set_live` now books the
   broker's ACTUAL weighted fill cost/proceeds (`get_fills`) instead of the
   pre-submit book estimate, at the both-fill persist, the naked-leg cost, and the
   unwind SELL proceeds. Closes Codex P1 (stale scan-time books understating live
   spend) + the deferred M-2.
2. **`delayed`→terminal poll (chunk 2)** — a non-terminal (`delayed`) CLOB accept is
   polled to a terminal state (`get_order`) before any halt, at all three ambiguous
   sites (YES, NO, unwind SELL). Only a *still*-ambiguous order halts.
3. **Set-aware crash-recovery reconciler (chunk 3)** — a scheduler job that resolves
   complete-set order rows left `pending`/`unknown` by a crash, plus the critical
   exclusion of complete-set legs from the directional order poller.

## 2. Current system architecture

```
book_complete_set_live (LIVE, behind 5 guards)
  YES FOK ─ _fill_status ─ AMBIGUOUS? ─ _poll_terminal_status(get_order) ─┐
  NO  FOK ─ _fill_status ─ AMBIGUOUS? ─ _poll_terminal_status ────────────┤ terminal
  unwind  ─ _fill_status ─ AMBIGUOUS? ─ _poll_terminal_status ────────────┘
  persist ─ _exact_fill_cost(get_fills) ─ ACTUAL weighted cost/proceeds ─> ledger+position

scheduler (every COMPLETE_SET_RECONCILE_INTERVAL_SEC, only if COMPLETE_SET_ARB_ENABLED)
  reconcile_complete_set_orders
    SELECT complete-set orders pending/unknown, no position, older than STALE_SEC
      ├─ broker not filled        -> mark 'cancelled' (no exposure)
      ├─ broker filled, untracked -> _persist_naked_halt (exact fills) + kill switch + page
      └─ unverifiable / ambiguous -> _halt_and_alert + page (operator reconciles)

OrderLifecycleManager.poll_once  (directional)
  SELECT ... AND strategy_type NOT LIKE 'complete_set_arb%'   <-- NEW: never touches set legs
```

The reconciler is set-aware: it never applies directional refund-on-cancel logic
(which would break a hedge), never silently deletes, and halts + pages on any
uncertainty rather than guessing. Reuses `_persist_naked_halt` / `_halt_and_alert`
/ `_fills_cost` (no duplication).

## 3. Files created / modified (full repo-root paths)

- Modified: `projects/polymarket/crusaderbot/domain/execution/complete_set_exec.py`
  (exact-fill helpers + integration; `_poll_terminal_status` + 3 ambiguous sites;
  broker-id on ambiguous `_mark_order`; `reconcile_complete_set_orders` +
  `_reconcile_one_order`).
- Modified: `projects/polymarket/crusaderbot/domain/execution/lifecycle.py`
  (directional poll SELECT excludes `complete_set_arb%`).
- Modified: `projects/polymarket/crusaderbot/config.py` (4 knobs: delayed-poll
  attempts/interval, reconcile stale/interval).
- Modified: `projects/polymarket/crusaderbot/scheduler.py`
  (`reconcile_complete_set` job + gated `add_job`).
- Created: `projects/polymarket/crusaderbot/tests/test_complete_set_reconcile.py`
- Modified: `projects/polymarket/crusaderbot/tests/test_complete_set_live.py`
  (FakeClob `get_fills`/`get_order`; exact-fill + delayed-poll tests).

No migration (reuses existing `orders`/`positions` schema; `strategy_type` from
mig 026, `paired_position_id` from mig 078).

## 4. What is working

- Exact fills override the estimate when the broker filled dearer; fall back to the
  estimate on incomplete/absent fills; never block the persist
  (`test_exact_fill_overrides_book_estimate`,
  `test_exact_fill_falls_back_to_estimate_on_incomplete_fills`,
  `test_unwind_exact_fill_proceeds`, `test_fills_cost_aggregates_and_skips_garbage`).
- `delayed` resolves to matched/unmatched before deciding; still-delayed halts
  (`test_yes_delayed_polls_to_matched_then_both_fill`,
  `test_no_delayed_polls_to_killed_then_unwinds`,
  `test_unwind_delayed_polls_to_matched_then_flat`,
  `test_yes_delayed_stays_ambiguous_halts`).
- Reconciler routes correctly: not-filled→cancel, filled→persist-naked+halt (exact
  cost), no-broker-id/ambiguous→halt; no-op in paper; isolates per-order errors;
  closes the client (`test_complete_set_reconcile.py`, 7 tests).
- Directional poller excludes complete-set legs (`test_lifecycle_excludes_...`); 57
  directional lifecycle tests still pass (no regression).
- 67 complete-set suite + 57 lifecycle + 38 config tests pass; ruff + py_compile
  clean. (Pre-existing unrelated failure: `test_builder_relayer` — missing optional
  SDK in this env, fails on clean main too.)

## 5. Known issues

- A crash-leftover order with a NULL broker id cannot be auto-verified (the booker
  keeps the hot YES→NO path latency-free and does not persist broker ids
  mid-flight); the reconciler conservatively HALTS + pages for operator reconcile in
  that case. This is the safe trade-off (visibility over silent auto-resolution),
  not a gap.
- If both legs of a pair filled but neither persisted (a rare double-crash), the
  reconciler tracks each as a force-exitable naked leg + halts — safe (exposure
  tracked) though the operator reconciles them back into a set manually.

## 6. What is next

- WARP•SENTINEL validation (MAJOR) → owner review/merge.
- After merge: the complete-set LIVE path has its full pre-flip safety net. The LIVE
  flip (operator sets the 5 guards + `COMPLETE_SET_ARB_ENABLED`) remains an
  owner-gated operational decision — optionally a small live-fire validation first.

---

### Validation Handoff (NEXT PRIORITY)

WARP•SENTINEL validation required for Lane 3C-2 (exact-fill + delayed-poll +
crash-recovery reconciler) before merge.
Source: projects/polymarket/crusaderbot/reports/forge/complete-set-arb-lane3c-reconcile.md
Tier: MAJOR
