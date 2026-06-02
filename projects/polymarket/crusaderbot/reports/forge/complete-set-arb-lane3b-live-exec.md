# Complete-Set Arbitrage — Lane 3B (LIVE two-leg FOK + naked-leg auto-unwind)

**Branch:** `WARP/ROOT/complete-set-arb-lane3b-live-exec`
**Role:** WARP•R00T (owner-directed: "Lane 3 complete" — phased 3A → 3B → 3C;
naked-leg fallback = auto-unwind, owner-decided)
**Validation Tier:** MAJOR (new LIVE execution / order path — AGENTS.md tier rule;
WARP•SENTINEL required before merge)
**Claim Level:** NARROW INTEGRATION (the LIVE booking primitive exists + is fully
unit-tested; it is UNWIRED — no scan/registry calls it. Routing is Lane 3C.)

> Lane 3 (LIVE two-leg) is built in phases behind the default-OFF activation
> guards. **This PR = Lane 3B: the LIVE execution primitive** —
> `book_complete_set_live`. Lane 3A (#1566) gave the live position INSERT its
> `active_preset` + `strategy_metadata`; 3B is the two-leg FOK booker that uses
> them. 3C (next) routes the scan's `chosen_mode == "live"` decision into it.

## 1. What was built

`domain/execution/complete_set_exec.py` — new `book_complete_set_live(...)` plus
supporting helpers. It books both legs (YES + NO) of one binary complete set LIVE
as a hedged pair, with an owner-directed auto-unwind fallback for the one-leg-only
fill case.

Execution state machine (SEQUENTIAL, not concurrent — sequencing minimises the
naked-exposure window and makes recovery deterministic):

1. `assert_live_guards(role, trading_mode)` — defense-in-depth re-check of all 5
   activation guards (+ `USE_REAL_CLOB` + `role=admin` + `trading_mode=live`). A
   miss raises `LivePreSubmitError` with **zero exposure**.
2. Degenerate guard (`fillable_shares <= 0` → `skipped`).
3. Idempotency precheck (`SELECT COUNT(*) ... idempotency_key = ANY(:yes,:no)`) →
   `duplicate` if either leg seen. Then claim both legs `pending`
   (`ON CONFLICT DO NOTHING`), mirroring `live.execute`.
4. Pre-submit CLOB metadata for BOTH legs (`tick_size`/`neg_risk`) — failure aborts
   pre-submit (no exposure). FOK BUY limits are recomputed from **live book depth**
   (`_buy_fill_limit` walks the ascending asks for the full-fill price + 1 tick);
   `None` (depth evaporated) aborts pre-submit. Arb invariant
   `yes_limit + no_limit < COMPLETE_SET_PAYOUT` enforced — a non-riskless set is
   never submitted.
5. **YES FOK.** Kill (no fill) → `no_fill` clean abort, the NO leg is **never
   submitted** → zero naked exposure. `ClobAuthError` → pre-submit abort.
   Other exception → ambiguous → kill-switch HALT + operator page +
   `LivePostSubmitError`.
6. YES filled → **NO FOK.** Both filled → persist the linked pair (2 positions
   `strategy_type=complete_set_arb` held-to-settlement + `paired_position_id`
   cross-link + 2 ledger debits, one atomic transaction) → audit + notify.
7. NO killed → the YES leg is **naked** → `_unwind_naked_leg`: aggressive FOK SELL
   (`_sell_fill_limit` crosses the bid down to flatten). Filled → flat (debit cost
   + credit proceeds at the conservative sell limit, **no open position**, realised
   spread loss audited, **trading continues**). Failed (no bid depth / FOK kill /
   broker error) → `_persist_naked_halt`.
8. `_persist_naked_halt` → persist the naked leg as
   `strategy_type=complete_set_arb_naked` (a DISTINCT string, NOT the
   held-to-settlement `complete_set_arb`, so the exit watcher does **not** hold it
   — it stays force-exitable by the operator / preset sweeps) + ledger debit (the
   capital really left) + `kill_switch.set_active(pause)` HALT + `notify_operator`
   page. Returns `naked_halt`.
9. NO leg `ClobAuthError` (signing failed, never hit the wire) is treated as a NO
   kill → unwind. NO leg ambiguous (other exception) → HALT + `LivePostSubmitError`
   and **no auto-unwind** (an unwind could over-sell if NO actually filled —
   operator reconciles).

Return contract: `open` / `no_fill` / `unwound` / `naked_halt` / `duplicate` /
`skipped`; `LivePreSubmitError` (safe abort) / `LivePostSubmitError` (ambiguous —
caller must never paper- or retry-duplicate).

## 2. Current system architecture

```
Lane 1  fillable_complete_set            -> CompleteSetQuote
Lane 2B book_complete_set_paper          -> PAPER pair (held to settlement)
Lane 3A live.execute active_preset+meta  -> live position carries pairing context
Lane 3B book_complete_set_live (THIS)    -> LIVE pair via 2x FOK + auto-unwind
Lane 3C scan chosen_mode=='live' routing -> calls 3B  [NEXT]

Pipeline: RISK (set-aware, gated once on combined cost)
          -> [EXECUTION: book_complete_set_live] -> redeem (settlement)
```

FOK is atomic per leg (matched | killed) — there is no partial-fill branch to
reconcile, which is what makes the sequential YES→NO→unwind machine tractable and
the naked case a single directional leg.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/execution/complete_set_exec.py`
  (new `book_complete_set_live` + `_unwind_naked_leg` + `_persist_naked_halt` +
  `_insert_live_order` / `_insert_live_position` / `_mark_order` / `_halt_and_alert`
  + fill/book helpers `_order_filled` / `_extract_order_id` / `_bids_descending` /
  `_buy_fill_limit` / `_sell_fill_limit`; new imports; `COMPLETE_SET_NAKED_STRATEGY`;
  expanded `__all__`)
- `projects/polymarket/crusaderbot/tests/test_complete_set_live.py` (new — 15 tests)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

15 new hermetic tests (no DB / broker / network — fake pool, fake CLOB, fake
market-data, captured kill-switch + operator pages) cover every branch:
both-legs-fill (linked pair + 2 debits + held-to-settle strategy), FOK-buy-limits
respect the arb budget, YES-kill clean abort (NO never sent), NO-kill →
unwind-success (flat, no halt, debit+credit), unwind sell crosses the bid down,
unwind-FOK-kill → naked_halt (persist `complete_set_arb_naked` + HALT + page),
no-bid-depth → halt without an extra submit, YES-ambiguous → halt +
LivePostSubmitError, NO-ambiguous-after-YES-fill → halt + no unwind, arb-invariant
reject, depth-insufficient abort, duplicate skip, non-positive skip, guard-failure
abort, metadata snapshot rides both legs. All 15 pass.

Regression: 112 related-area tests pass
(`test_complete_set_exec` / `test_complete_set_scan` / `test_live_execution_rewire`
/ `test_exit_watcher`). `ruff check` + `py_compile` clean on both files.

## 5. Known issues / scope boundaries

- **UNWIRED.** `grep` confirms zero callers — the complete-set scan still skips a
  `chosen_mode == "live"` decision (`complete_set_live_not_wired_skipping` at
  `complete_set_scan.py:237`). Routing is Lane 3C. Runtime risk is therefore zero:
  even with `COMPLETE_SET_ARB_ENABLED` ON and all guards flipped, nothing reaches
  `book_complete_set_live` until 3C lands.
- Crash recovery is the existing `live.execute` posture: the `pending`/`unknown`
  order rows + operator alerts are the durable breadcrumb; a full automatic
  on-chain reconciler is a separate concern. The idempotency claim prevents a
  re-scan from double-submitting; an in-flight ambiguous pair halts + pages rather
  than blindly resubmitting.
- The unwind proceeds are booked at the (conservative) sell limit price — FOK fills
  at limit-or-better, so the credited balance is never overstated. Exact realised
  fill reconciliation is operator/ledger-sweep territory, not this primitive.

## 6. What is next

- **Lane 3C (MAJOR, WARP•SENTINEL):** route `complete_set_scan`
  `chosen_mode == "live"` to `book_complete_set_live` (pass
  `yes_book`/`no_book`/`role`/`trading_mode`), behind `COMPLETE_SET_ARB_ENABLED` +
  the 5 activation guards. Last wiring step to make the LIVE path reachable.

---

- **Validation Tier:** MAJOR (new LIVE execution / order path)
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** `book_complete_set_live` two-leg FOK state machine —
  clean abort, both-fill pair persistence, naked-leg auto-unwind, naked-halt
  fallback, arb/depth/idempotency pre-submit guards, ambiguous post-submit halts.
- **Not in Scope:** scan→live routing (Lane 3C), automatic on-chain crash
  reconciliation, exact-fill ledger reconciliation, redemption/settlement path.
- **Suggested Next Step:** WARP•SENTINEL validation (MAJOR, live path) → owner merge
  (LIVE-touching — owner confirms); then Lane 3C wiring.

### Validation Handoff (NEXT PRIORITY)

WARP•SENTINEL validation required for Lane 3B (LIVE two-leg FOK + naked-leg
auto-unwind) before merge.
Source: projects/polymarket/crusaderbot/reports/forge/complete-set-arb-lane3b-live-exec.md
Tier: MAJOR
