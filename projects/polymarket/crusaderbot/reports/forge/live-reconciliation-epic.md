# WARP•FORGE Report — LIVE reconciliation epic (WARP-74)

Tracks: Linear WARP-74 (P0 for real-money live). Source audit: WARP-73 (PR #1610).
Role: WARP•R00T (execution hardening). Branch: `claude/cool-hamilton-KaLWA`
(pre-declared by the session orchestration layer for this task).

Validation Tier: **MAJOR** (execution / risk / capital path)
Claim Level: **NARROW INTEGRATION** (new reconcile/kill-cancel/drift mechanisms
wired into scheduler + live close path; verified hermetically, not yet exercised
against a live broker on Fly)
Validation Target: the three WARP-73 P0 gaps closed without weakening any
existing protection gate, on the LIVE path only.
Not in Scope: paper-path behaviour (unchanged), complete-set reconciler
(untouched — keeps its own set-aware logic), auto-reconstruction of a fuzzily
size/price-matched untracked fill (deliberately deferred — see Known issues),
any real-money LIVE flip (owner decision; gated by WARP•SENTINEL).

---

## 1. What was built

The WARP-73 audit returned NOT-READY for real-money live with three P0 gaps.
This epic closes all three across chunks A/B/C, on the live path only.

**Chunk A (P0 #1 + #2) — generalized live reconciler.** New module
`domain/execution/live_reconcile.py` with two scheduler-driven sweeps that close
the exact states the two existing reconcilers do NOT own:

- `reconcile_live_orders` — directional `mode='live'` orders orphaned in
  `status='unknown'` (an ambiguous post-submit that `live.execute` marks with NO
  broker id, so the lifecycle poller's `STATUS_OPEN` never selects it). For
  `late_entry_v3` / `signal_following` / `copy_trade` only (never complete-set),
  it resolves each against broker truth: a single untracked resting order on the
  order's token is **adopted** back into the lifecycle poller (re-link broker id,
  flip `unknown→pending`) ONLY after its size + price match the unknown order
  (price mandatory; size tolerant of raw vs 1e6 fixed-math and the aggressive
  +1-tick limit) — a size/price mismatch **pages** instead (likely an unrelated
  order); multiple untracked matches **halt + page**; an unverifiable order
  **pages once** for manual reconcile (stamped so it does not re-page each sweep).
  Never auto-cancels (an instant-fill could hide real exposure) and never
  fabricates a position.
- `reconcile_closing_positions` — live positions stranded in `status='closing'`
  by a crash between the close SELL and the finalize. Runs ONCE at startup (every
  `closing` row at boot is a crash leftover) and periodically for rows whose
  `closing_at` is older than `LIVE_CLOSING_STALE_SEC`. Acts ONLY on a TERMINAL
  broker state: a fully-filled SELL **finalizes to `closed` + credits the ledger**
  (proceeds from real fills); a terminal-KILLED with zero fills **rolls back to
  `open`** for a clean exit-watcher retry; a terminal-KILLED with a PARTIAL fill
  **pages** (`paged_partial_close` — never finalize and strand the unsold
  remainder); a non-terminal close (even one partially filled in flight) **pages**
  and is left `closing` for the next sweep — never premature-finalized.

To make closing-recovery possible, migration `082` adds `positions.closing_at`
(set in the atomic close claim) and `positions.close_order_id` (persisted
immediately after the close SELL, before the finalize — shrinking the crash blind
window to the gap between `post_order` returning and that one UPDATE).

**Chunk B (P0 #3) — kill switch broker-cancel.** `kill_switch_exec.py` now calls
`client.cancel_all_orders()` (global broker cancel) BEFORE the DB-cancel cascade,
so resting GTC orders are pulled off Polymarket — not just marked cancelled in the
DB. Paper / non-live is a no-op. The cancel is best-effort (never blocks the kill
sequence); a FAILED broker cancel is recorded in the audit reason and pages the
operator with an explicit "resting orders may still be LIVE — cancel manually"
warning, removing the false-safety where STOP looked clean while exchange orders
kept filling.

**Chunk C (P1) — drift detector + paper-fallback instrumentation.**
- New `domain/execution/drift_detector.py` `detect_order_drift` — a periodic,
  alert-only sweep comparing the broker's open-orders set against the DB's
  believed-open set. broker-only ids (untracked resting exposure) and db-only ids
  (phantom open) page the operator + audit. Never mutates orders.
- `router.py` now classifies a `LivePreSubmitError` paper fallback: an
  INFRA-DEGRADED fallback (CLOB market-data unavailable, client config/auth
  error, idempotency read failed, or `USE_REAL_CLOB` off while guards on) is
  audited distinctly as `live_infra_degraded_paper_fallback` + logged CRITICAL +
  pages the operator, so a live operator is never silently downgraded to paper
  (GAP #5). A DELIBERATE fallback (guard intentionally off) keeps the existing
  `live_blocked_fallback_paper` audit.

## 2. Current system architecture

```
DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING

EXECUTION (live):
  live.execute --(ambiguous post-submit)--> orders.status='unknown'  ─┐
  lifecycle.poll_once  owns ('submitted','pending','partial_filled')  │
  complete_set reconciler owns 'complete_set_arb%'                     │
  ── NEW: live_reconcile.reconcile_live_orders owns directional        │
         'unknown' (adopt / halt+page / page)  <─────────────────────-─┘
  live.close_position: claim status='closing' (+closing_at) -> SELL
         -> persist close_order_id -> finalize 'closed'
  ── NEW: live_reconcile.reconcile_closing_positions recovers a
         crash-stranded 'closing' row (finalize / rollback / page)

RISK:
  kill_switch_exec.execute_kill_switch:
     ops set_active(pause)
   + NEW broker cancel_all_orders()  (real exchange halt)
   + DB cancel pending + system flag + audit + operator page

MONITORING:
  ── NEW: drift_detector.detect_order_drift (broker<->DB open-order drift, alert)
  ── NEW: router live_infra_degraded_paper_fallback (distinct audit + page)
```

All new sweeps no-op in paper/non-live (`USE_REAL_CLOB` gate), never raise (safe
on APScheduler), and never weaken an existing gate (RISK still runs before
EXECUTION; Kelly, `$10k` floor, `ENABLE_LIVE_TRADING`, slippage guard untouched).

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/082_live_reconcile_closing.sql`
- `projects/polymarket/crusaderbot/domain/execution/live_reconcile.py`
- `projects/polymarket/crusaderbot/domain/execution/drift_detector.py`
- `projects/polymarket/crusaderbot/tests/test_live_reconcile.py`
- `projects/polymarket/crusaderbot/tests/test_kill_switch_broker_cancel.py`
- `projects/polymarket/crusaderbot/tests/test_order_drift_detector.py`
- `projects/polymarket/crusaderbot/tests/test_router_infra_fallback.py`

Modified:
- `projects/polymarket/crusaderbot/domain/execution/live.py` (closing_at in the
  close claim; persist close_order_id after the SELL)
- `projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py` (broker
  cancel_all_orders + operator escalation on failure)
- `projects/polymarket/crusaderbot/domain/execution/router.py` (infra-degraded
  fallback classification + distinct audit/page)
- `projects/polymarket/crusaderbot/scheduler.py` (register live reconcile,
  closing reconcile periodic + startup, drift detect jobs)
- `projects/polymarket/crusaderbot/config.py` (LIVE_RECONCILE_* / LIVE_CLOSING_* /
  ORDER_DRIFT_* knobs)

## 4. What is working

Hermetic test evidence (touched execution/risk suites green; the 4 new suites =
31 passed after the review round):
- `reconcile_live_orders`: paper no-op; disabled no-op; no-rows no-op; unique
  size/price-matching resting order **adopted** (broker id re-linked,
  `unknown→pending`, audit); size/price **mismatch → page** (not adopted);
  multiple untracked **halt + kill switch engaged**; already-tracked resting
  order ignored → page; no resting order → page-once + stamp; broker query
  failure → page (never assume).
- `reconcile_closing_positions`: terminal full fill → `closed` + ledger credit
  (proceeds from real fills); terminal-KILLED zero fills → rollback to `open`;
  terminal-KILLED partial fill → `paged_partial_close` (no finalize, no credit);
  non-terminal (incl. in-flight partial) → stays `closing` + page, no credit;
  missing close_order_id → page; broker query failure → page.
- Kill switch: paper no-op; live `cancel_all_orders` called + client closed;
  broker-cancel failure contained (client still closed) AND operator warned
  ("BROKER CANCEL FAILED"); `execute_kill_switch` invokes the broker cancel.
- Drift detector: paper/disabled no-op; clean → no page; broker-only and db-only
  drift → page + `order_drift_detected` audit; broker query failure contained.
- Router: infra fragments classified vs deliberate reasons; infra-degraded path
  audits `live_infra_degraded_paper_fallback` + pages + still paper-falls-back;
  deliberate path keeps `live_blocked_fallback_paper`.
- Regression: existing `test_live_execution_rewire`, `test_kill_switch`,
  `test_kill_switch_paths`, `test_complete_set_reconcile`, `test_order_lifecycle`,
  `test_exit_watcher` all green — the close-path `closing_at`/`close_order_id`
  writes did not disturb the claim/finalize race semantics.
- `ruff check` clean on all touched modules + tests; `py_compile` clean.

## 5. Known issues

- **Live-broker proof pending.** Verified hermetically (fake pool + fake CLOB).
  The adopt/finalize/rollback/cancel paths have NOT been exercised against a real
  Polymarket broker on Fly — that is the WARP•SENTINEL + owner gate before any
  real-money flip. Acceptance criteria (simulated crash → no orphan; STOP cancels
  resting GTC) need a staging run.
- **`'unknown'` instant-fill not auto-reconstructed.** When a directional
  `unknown` order shows no resting order, the submit either never landed or
  instant-filled. We page for manual reconcile rather than fabricate a position
  from a fuzzy size/price match (SENTINEL-safe). A future enhancement could attach
  a market-trade scan keyed to the signer to auto-recover the instant-fill case.
- **`close_order_id` blind window.** A crash in the sub-millisecond gap between
  `post_order` returning and the `close_order_id` UPDATE leaves a `closing` row
  with no id → the reconciler pages (never assumes). Acceptable; documented.
- Container lacks several runtime deps for the full suite (fastapi, etc.) — 20
  pre-existing collection errors unrelated to this lane (per PROJECT_STATE).
  graphify CLI unavailable → AST graph update skipped.

## 6. What is next

- WARP•SENTINEL MAJOR validation against code truth (this is execution + capital
  path). Verify: no gate weakened; reconcilers never raise; closing recovery never
  double-sells; kill broker-cancel best-effort + escalation correct.
- Apply migration `082` to Supabase production before the lane runs live.
- Owner: staging run to satisfy the WARP-74 acceptance (simulated crash recovery
  + STOP-cancels-resting-GTC proof), then the real-money LIVE flip decision.

Suggested Next Step: WARP•SENTINEL validation of the live reconcile/kill-cancel/
drift epic before merge; then Fly staging proof of the three acceptance criteria.
