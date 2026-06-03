# WARP•FORGE — complete-set-arb-lane3c-live-wire

Branch: `WARP/ROOT/complete-set-arb-lane3c-live-wire`
Role: WARP•FORGE
Validation Tier: **MAJOR** (makes a LIVE order path reachable from the scan loop)
Claim Level: **NARROW INTEGRATION**
Validation Target: `services/signal_scan/complete_set_scan.py` chosen_mode dispatch —
paper vs live booker routing, the live argument set, `booked` accounting per live
outcome, ambiguous-raise isolation, and the unknown-mode skip.
Not in Scope: the H-2/M-2 reconciliation work (crash-recovery reconciler,
`delayed`→terminal poll, exact-fill parsing) — that is Lane 3C-2; the live booker
internals (Lane 3B, merged #1568); redemption/settlement.
Suggested Next Step: WARP•SENTINEL validation (MAJOR, live path reachable) → owner
review/merge; then build Lane 3C-2 (reconciler) before any LIVE flip.

---

## 1. What was built

Lane 3C-1 — the wiring that connects the complete-set scan to the **LIVE** booking
primitive built in Lane 3B. Previously the scan booked PAPER only and explicitly
**skipped** any non-paper gate decision (`complete_set_live_not_wired_skipping`).
Now `scan_complete_set_for_user` dispatches on the risk gate's `chosen_mode`:

- `"paper"` → `book_complete_set_paper(...)` (unchanged call/accounting).
- `"live"`  → `book_complete_set_live(...)`, threading the four arguments the live
  primitive needs that the paper one omits: `role`, `trading_mode`, `yes_book`,
  `no_book` (all already in scope at the dispatch point).
- any other value → skip + `complete_set_unknown_mode_skipping` (defensive; counts
  as rejected, never executed).

The live path remains inert: `book_complete_set_live` re-asserts all 5 LIVE
activation guards itself, and the whole branch is still behind
`COMPLETE_SET_ARB_ENABLED` (default OFF). **Wiring alone does not make it live** —
flipping the guards ON is a separate, explicit operator action, and Lane 3C-2
(reconciler) is the mandatory pre-condition before that flip.

## 2. Current system architecture

```
signal_scan_job.run_once  (Phase B3, behind COMPLETE_SET_ARB_ENABLED)
  └─ scan_complete_set_for_user(row, markets, settings)        # live_booker defaulted
       per market:
         DATA   get_book(yes) ∥ get_book(no)
         SIGNAL fillable_complete_set → CompleteSetQuote | None
         LOG    complete_set_quote (before any capital)
         RISK   gate.evaluate(complete_set=True)  → GateResult.chosen_mode
         EXEC   chosen_mode == "paper" → book_complete_set_paper
                chosen_mode == "live"  → book_complete_set_live   ← NEW (3C-1)
                                          (role, trading_mode, yes_book, no_book, …)
                else                    → skip (unknown_mode)
```

`booked` accounting for the live branch maps the booker's return `status`:

| live `status` | persisted a position? | `res.booked` |
| --- | --- | --- |
| `open` (both legs filled) | yes (pair) | +1 |
| `naked_halt` (naked leg persisted + halt) | yes (force-exitable row) | +1 |
| `no_fill` (clean YES kill) | no | +0 |
| `unwound` (naked leg flattened) | no open position | +0 |
| `duplicate` / `skipped` | no | +0 |
| raises `LivePostSubmitError` (ambiguous; already halted + paged) | — | per-market `errors` +1 |

A new `live_booker: Booker = book_complete_set_live` dependency-injection param
mirrors the existing `booker` param, so the `run_once` call site is unchanged and
tests can inject a fake live booker.

## 3. Files created / modified (full repo-root paths)

- Modified: `projects/polymarket/crusaderbot/services/signal_scan/complete_set_scan.py`
  (module docstring 2C-2b→3C-1; import `book_complete_set_live`; `live_booker` DI
  param; chosen_mode dispatch replacing the live-skip branch).
- Modified: `projects/polymarket/crusaderbot/tests/test_complete_set_scan.py`
  (replaced the obsolete `test_live_decision_is_skipped_not_executed`; added 5
  live-path tests + `_LiveBooker` fake + `_approve_live`).
- Modified: `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- Modified: `projects/polymarket/crusaderbot/state/CHANGELOG.md`
- Created: `projects/polymarket/crusaderbot/reports/forge/complete-set-arb-lane3c-live-wire.md`

No migration (reuses Lane 2A/3A schema). No change to `signal_scan_job.py` (the
call site uses the defaulted `live_booker`).

## 4. What is working

- Live gate decision routes to `book_complete_set_live` with role/trading_mode/both
  books; paper primitive is not called on a live decision
  (`test_live_decision_routes_to_live_booker`).
- `booked` increments only for persisted outcomes: `open`/`naked_halt` count;
  `no_fill` does not (`test_live_no_fill_books_nothing`,
  `test_live_naked_halt_counts_as_booked`).
- An ambiguous live raise is isolated to the market as an error, not a batch crash
  (`test_live_booker_raise_isolated_to_market`).
- An unrecognised `chosen_mode` is skipped, never executed
  (`test_unknown_chosen_mode_skipped_not_executed`).
- Live status is classified, not bucketed: `open`/`naked_halt` → booked
  (`naked_halt` also emits a `complete_set_live_naked_halt` warning); known clean
  no-ops (`no_fill`/`unwound`/`duplicate`/`skipped`) → silent; **persist-failure
  (`naked_halt_persist_failed`) and any unrecognised status → `res.errors` + a
  `complete_set_live_unreconciled` error log** (safe-by-default), so an untracked
  live leg can never be masked as a clean run in `signal_scan_job` telemetry
  (Codex P2, fixed in-lane: `test_live_naked_halt_persist_failed_is_error`,
  `test_live_unknown_status_is_error_safe_by_default`).
- Paper path + dormant-margin/capital/gate-reject behaviour unchanged (existing
  suite green).
- 18 `test_complete_set_scan` + 51 related (scan/live/exec/gate_rescope) pass;
  ruff + py_compile clean on both modified production files.

## 5. Known issues

- **Lane 3C-2 (MANDATORY before LIVE flip), per SENTINEL H-2/M-2:** no automatic
  crash-recovery reconciler yet — a crash between a confirmed fill and the persist
  txn leaves `pending`/`unknown` order rows that are currently operator-reconciled;
  a `delayed` CLOB accept currently halts rather than polling to terminal; unwind
  proceeds are a pre-submit-book estimate, not the broker's exact fill. These are
  the explicit Lane 3C-2 deliverables. The live path must not be flipped ON until
  3C-2 lands.
- **Stale scan-time books on the live path (Codex P1 on this PR) — deferred to
  3C-2.** The scan passes the books it fetched at scan time into
  `book_complete_set_live`, which derives the FOK limits + recorded weighted cost
  from them. If the book drifts adversely between scan and submission but the FOK
  still fills, actual spend can exceed the recorded/gate-approved weighted cost
  (bounded above by the FOK limit). The authoritative fix — persist from the
  broker's actual fill details (and/or refetch+recompute immediately before submit)
  — is the same exact-fill reconciliation as M-2 and is owned by Lane 3C-2. A bare
  pre-submit refetch still races the real fill, so it is not a sufficient
  wiring-lane fix. Unreachable until the operator flips the guards + flag, which is
  gated on 3C-2.
- The live branch is unreachable in practice until the operator flips
  `COMPLETE_SET_ARB_ENABLED` + the 5 activation guards; runtime risk today = zero.

## 6. What is next

- **Lane 3C-2 (MAJOR, WARP•SENTINEL):** `WARP/ROOT/complete-set-arb-lane3c-reconcile`
  — crash-recovery reconciler + `delayed`→terminal poll + exact-fill parsing. This
  is the final pre-LIVE-flip pre-condition for the complete-set arb epic.

---

### Validation Handoff (NEXT PRIORITY)

WARP•SENTINEL validation required for Lane 3C-1 (scan→live wiring; LIVE path now
reachable behind guards) before merge.
Source: projects/polymarket/crusaderbot/reports/forge/complete-set-arb-lane3c-live-wire.md
Tier: MAJOR
