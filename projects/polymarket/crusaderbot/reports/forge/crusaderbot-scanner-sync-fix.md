# WARP•FORGE REPORT — crusaderbot-scanner-sync-fix

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: demo scanner self-seeding + scheduler.sync_markets outcomePrices parse fix
Not in Scope: copy_trade path, live Heisenberg path, risk gate, execution engine

---

## 1. What Was Built

Fixed two bugs that together caused every signal_following candidate to be logged
as `skipped_market_not_synced`, producing zero trades on every scanner tick.

**Bug A — scheduler.sync_markets() silently fails on every market (outcomePrices parse)**

`scheduler.sync_markets()` read `outcomePrices` as a raw value and passed it directly
to `float(outcomes[0])`. Polymarket Gamma API returns `outcomePrices` as a JSON-encoded
string (e.g. `'["0.565","0.435"]'`), not a list. `outcomes[0]` evaluates to `'['` (first
character of the string) → `ValueError` per market → exception caught silently →
0 rows ever inserted into `markets` table.

The same bug was already fixed in `market_signal_scanner.py` (lines 363–368) in a
prior lane. `scheduler.sync_markets()` was missed.

**Bug B — scanner never seeds markets table (race condition)**

`market_signal_scanner.run_job()` (demo path) fetches markets from the Polymarket API,
applies edge-finding logic, and publishes approved markets to `signal_publications` using
`conditionId` as `market_id`. It never wrote those markets to the `markets` table.

`signal_scan_job._process_candidate()` calls `_load_market(cand.market_id)` which queries
`SELECT * FROM markets WHERE id = $1`. With `markets` empty (Bug A) or not yet synced
(race window), every candidate returns None → `skipped_market_not_synced`.

Fix: upsert the market into `markets` immediately before publishing the signal. This is
atomic with the scan tick — no race window, no dependency on `sync_markets` interval.

---

## 2. Current System Architecture

```
Polymarket API
    |
    v
market_signal_scanner.run_job() [60s interval]
    |-- edge_finder filter (price, liquidity, edge_bps)
    |-- APPROVED:
    |   |-- _upsert_market()  <-- NEW: seeds markets table atomically
    |   |-- _publish() → signal_publications
    |
    v
sf_scan_job.run_once() [180s interval]
    |-- evaluate_publications_for_user() → SignalCandidate list
    |-- _load_market(cand.market_id) → markets table  <-- now populated
    |-- TradeEngine.execute() → risk gate → paper fill
    |-- execution_queue INSERT → position OPEN
```

`scheduler.sync_markets()` [300s interval] is now also fixed to parse outcomePrices
correctly, keeping the markets table up to date between scanner ticks.

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py`
  — Added `_upsert_market()` helper (lines 99–152)
  — Wired `_upsert_market()` call before `_publish()` in demo path (lines 479–484)

- `projects/polymarket/crusaderbot/scheduler.py`
  — Fixed `sync_markets()` outcomePrices JSON string parsing (lines 62–68)

---

## 4. What Is Working

- `market_signal_scanner.py` scanner tests: 11/11 pass
- Syntax validation: both files parse clean
- `_upsert_market()` uses ON CONFLICT (id) DO UPDATE — idempotent and safe to retry
- `scheduler.sync_markets()` now correctly parses outcomePrices as JSON string
- Fix is isolated to demo/signal_following path — copy_trade and live Heisenberg
  paths are unchanged
- `_upsert_market()` failure is non-fatal — logged as warning, `_publish()` continues
  (dedup gate in signal_scan_job catches any leftover gap)

---

## 5. Known Issues

- Token IDs (`yes_token_id`, `no_token_id`) from Polymarket Gamma `get_markets()` endpoint
  may be absent for some markets (depends on API response shape). ON CONFLICT rule uses
  COALESCE so existing token_id data is preserved on refresh. Markets without token_ids
  can still be traded in paper mode (price is read from market row, not CLOB fill).
- `sync_markets()` outcomePrices fix requires the Polymarket API to be reachable.
  If the API is down, `sync_markets()` still returns 0 upserts — same as before, but
  now correctly for the right reason.

---

## 6. What Is Next

- WARP🔹CMD review of this STANDARD tier PR
- Observe next scanner tick logs for `scanner_market_upsert_failed` (should be absent)
- Confirm signal_scan_job logs show `outcome=accepted` or `outcome=rejected` (risk gate)
  instead of `outcome=skipped_market_not_synced`
- Confirm `published > 0` in `signal_scan_tick_done` log event

---

Suggested Next Step: WARP🔹CMD review. After merge, monitor one scanner tick in
production logs for `skipped_market_not_synced` count to confirm it reaches 0.
