# WARP•FORGE — real-market-settlement-fix

Branch: claude/crusaderbot-signal-scan-debug-Xnckj
Role: WARP•FORGE
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION (code + unit/DB-logic validation; full live-runtime proof requires Fly deploy + scheduler ticks)
Validation Target: resolution/settlement reachability, real-market scan routing, pending_settlement state machine, exposure accounting.
Not in Scope: executing the production data ops (voiding 25 demo positions, migrating 6 user subscriptions) — prepared but deliberately NOT run; the dormant Heisenberg live path (left as optional enrichment); the deferred edge-model bug #1 (edge = |price-0.5|).

---

## 1. What was built

Three fixes that, together, make CrusaderBot paper trading run on REAL,
officially-resolvable Polymarket markets and actually settle them — resolving
the closed-beta report that the bot "holds the same ~5 positions forever, makes
no profit, and never frees a slot."

FIX1 — CRITICAL settlement-reachability bug. `integrations/polymarket.py::get_market()`
fetched `GET /markets/{market_id}` as a path segment. The Gamma API returns
**422 Unprocessable Entity** for hex conditionIds in that form (documented in
the sibling `get_live_market_price`, which already uses the correct query form).
Because `markets.id` IS the hex `condition_id` everywhere it is written
(`market_signal_scanner._upsert_market` and `jobs/market_sync.py` both key on
condition_id), `detect_resolutions -> _process_market_resolution -> get_market()`
422'd on every single position. The market was therefore never observed as
`closed=true`, so no position ever settled and every concurrency slot stayed
locked permanently. Rewrote `get_market()` to use
`GET /markets?conditionId={id}` (query param + list-extract), mirroring the
proven `get_live_market_price` path.

FIX2 — real-market scan routing (owner directive: paper must trade real markets,
is_demo=true reserved for tests/dev). The edge-finder scan already pulls real
Polymarket data (real conditionId / outcomePrices / liquidity) but mislabeled
everything `is_demo=TRUE` and routed it to the Demo Feed. It now publishes real
markets to the **LIVE feed with is_demo=FALSE by default**, gated by a new
`SCANNER_DEMO_FEED_ENABLED` config flag (default **False**; set True only for
hermetic tests / local dev, where it restores the synthetic is_demo=TRUE /
demo-feed behaviour).

FIX3 — `pending_settlement` state. When a real market is past its
`resolution_at` but Polymarket has not yet posted the official close, the
position is flipped `open -> pending_settlement` instead of being left silently
`open` or (forbidden) flat-closed. It is never marked from last price, stays
counted against the user's exposure so it does not falsely free a slot, is
re-checked on every detection tick, and settles normally the moment the official
`closed=true` arrives.

Important: settlement was ALREADY official-resolution-only (it reads the winning
side from `outcomePrices` only after `closed=true`) and already never fabricated
PnL or flat-closed on expiry. The only defect was FIX1's 422 making that correct
check unreachable.

---

## 2. Current system architecture

```
SCAN (jobs/market_signal_scanner.run_job)
  edge-finder: polymarket.get_markets() [REAL Gamma data]
    -> SCANNER_DEMO_FEED_ENABLED ? (DEMO_FEED, is_demo=TRUE)   [tests/dev only]
                                 : (LIVE_FEED, is_demo=FALSE)  [PRODUCTION DEFAULT]
    -> _upsert_market(is_demo=<same>) -> _publish(feed, is_demo=<same>)
  heisenberg path: optional enrichment, dormant without HEISENBERG_API_TOKEN

SETTLE (services/redeem/redeem_router.detect_resolutions, scheduler @ RESOLUTION_CHECK_INTERVAL)
  candidate scan: positions status IN ('open','pending_settlement')
                  OR (closed AND resolution_at < NOW())
  _process_market_resolution(market_id):
    m = polymarket.get_market(market_id)   # FIX1: ?conditionId= (no 422)
    if not closed: _mark_pending_settlement(market_id); return   # FIX3
    else: classify winners/losers -> settle_* (status IN open/pending_settlement)

EXPOSURE (domain/risk/gate.py)
  _open_position_count / _open_exposure count status IN ('open','pending_settlement')
  -> max_concurrent + correlated-exposure gates stay honest
```

---

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/integrations/polymarket.py — FIX1: get_market() query form.
- projects/polymarket/crusaderbot/jobs/market_signal_scanner.py — FIX2: edge-finder routes to LIVE feed / is_demo=FALSE by default; docstring + logs updated.
- projects/polymarket/crusaderbot/config.py — FIX2: SCANNER_DEMO_FEED_ENABLED flag (default False).
- projects/polymarket/crusaderbot/services/redeem/redeem_router.py — FIX3: candidate query, _mark_pending_settlement helper, settle_* WHERE clauses.
- projects/polymarket/crusaderbot/domain/risk/gate.py — FIX3: exposure queries count pending_settlement.
- projects/polymarket/crusaderbot/tests/test_market_signal_scanner.py — 2 new feed-routing tests + fake-cfg field.
- projects/polymarket/crusaderbot/tests/test_redeem_workers.py — 2 new pending_settlement tests.

State:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md — surgical (Last Updated, Status, IN PROGRESS, NEXT PRIORITY).
- projects/polymarket/crusaderbot/state/WORKTODO.md — lane entry.
- projects/polymarket/crusaderbot/state/CHANGELOG.md — lane closure entry.

No schema migration required: positions.status is VARCHAR(20) with no CHECK constraint, so 'pending_settlement' needs no DDL.

---

## 4. What is working

- get_market() resolves hex conditionIds without 422 (query form, list-extract).
- Scanner publishes real markets to the LIVE feed with is_demo=FALSE by default; demo path only under SCANNER_DEMO_FEED_ENABLED.
- pending_settlement transition + settle-from-pending + exposure counting.
- Tests: 18 test_redeem_workers (2 new), 13 test_market_signal_scanner (2 new), 62 signal/pipeline; broader run 257 passed.
- Guards untouched: ENABLE_LIVE_TRADING=false, paper-only, RISK before EXECUTION.

## 5. Known issues

- One pre-existing, unrelated test failure: tests/test_activation_handlers.py fails on `api/health.py` fastapi import (module absent in this container) — fails identically on clean HEAD; not caused by this lane.
- pending_settlement positions drop out of the status='open' display in portfolio_snapshots / daily_report (capital still counted in the gate). Cosmetic; a follow-up could surface a distinct "pending settlement" bucket in the UI.
- Live-runtime proof (scheduler actually publishing is_demo=FALSE candidates and settling a closed market end-to-end) requires a Fly deploy — not runnable in this container.

## 6. What is next

- WARP•SENTINEL MAJOR validation (resolution reachability / scan routing / pending_settlement / exposure / guards).
- WARP🔹CMD authorize the PENDING PROD DATA OPS before they touch the live DB (owner already chose the intent):
  - Void the 25 stuck demo positions: return stake, pnl_usdc=0, exit_reason='demo_retired', redeemed=TRUE (explicit cleanup, NOT a market resolution). Reviewable SQL to be attached.
  - Migrate the 6 beta users' subscriptions Demo Feed -> Live Feed so they receive the new real-market signals.
- Post-merge: Fly.io redeploy; confirm a scanner tick publishes LIVE-feed is_demo=FALSE candidates and detect_resolutions settles a closed market.

---

Suggested Next Step: WARP•SENTINEL audit this lane (MAJOR), then WARP🔹CMD sign-off on the two production data ops.
