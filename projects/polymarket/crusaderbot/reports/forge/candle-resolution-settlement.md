# WARP•FORGE Report — Candle Resolution + Settlement

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: resolution detection + settlement for crypto up/down candle markets (and the broader get_market mis-targeting bug it exposed).
- Not in Scope: live on-chain redemption changes; the redeem/settle primitives themselves (unchanged); non-candle market behavior beyond the get_market correctness fix.
- Suggested Next Step: WARP•SENTINEL MAJOR validation, then Fly redeploy + confirm the 5 stuck positions settle and `markets.resolved` flips for past-due updown markets.

---

## 1. What was built

Fix for the owner report: "Close Sweep positions just open but don't close at end
time." Diagnosed against the live DB + Gamma API:

- `markets` holds **778** `*-updown-*` candle markets; **0** ever `resolved`, **732**
  past-due. Five positions sit `status='open'` well past their `resolution_at`.
- Probing Gamma showed `GET /markets?conditionId=<hex>` (singular) is **silently
  ignored** — it returns the default 20-market list (first row an unrelated
  "Rihanna" market) for *any* conditionId, including `0xdeadbeef`. The plural
  `?condition_ids=` filters correctly (returns exactly the requested market).
- Candle markets are **not indexed under `/markets` at all** (`condition_ids`
  returns empty); they exist only under `GET /events?slug=`, where the candle
  correctly reports `closed:true`, `umaResolutionStatus:resolved`, and
  `outcomePrices:'["1","0"]'` (a JSON **string**).

So `detect_resolutions → _process_market_resolution → get_market` was reading the
wrong market on every tick, never observed `closed=true`, and nothing ever settled.

Three fixes:
1. **`get_market`** now queries the correct plural `?condition_ids=` **and validates**
   the returned row's `conditionId` equals the requested id (returns None on mismatch),
   so settlement can never target the wrong market.
2. **`get_event_market_by_slug(slug)`** (new) resolves candle markets from `/events`;
   `_process_market_resolution` falls back to it (conditionId-validated) when
   `get_market` is None.
3. **`_coerce_outcome_prices()`** (new) parses `outcomePrices` whether it arrives as a
   JSON string or a list, so classification doesn't crash on candle data.

The existing settlement primitives (`settle_winning_position`,
`settle_losing_position`, `_mark_pending_settlement`) are unchanged — they already
handle `open`/`pending_settlement`. The five stuck positions auto-settle on the next
resolution tick after deploy.

## 2. Current system architecture

Resolution flow (scheduler `check_resolutions`, every `RESOLUTION_CHECK_INTERVAL`=300s):
`detect_resolutions` selects candidate `(market_id, slug)` for unresolved markets with
redeemable positions → `_process_market_resolution(market_id, slug)`:
1. `m = get_market(market_id)` (now `?condition_ids=` + conditionId validation).
2. If `m is None and slug`: `m = get_event_market_by_slug(slug)`, accepted only if its
   nested `conditionId` matches `market_id`.
3. If `m` missing/not `closed` → `_mark_pending_settlement` (unchanged).
4. `outcomes = _coerce_outcome_prices(m["outcomePrices"])`; `winning = yes if
   outcomes[0] > 0.5 else no`.
5. Per position: loser → `settle_losing_position`; winner → `_enqueue_redeem`
   (instant worker fired for instant mode). On clean classification, flip
   `markets.resolved=TRUE, winning_side`.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/integrations/polymarket.py
  (`get_market` → `condition_ids` + conditionId validation; new `get_event_market_by_slug`)
- projects/polymarket/crusaderbot/services/redeem/redeem_router.py
  (`detect_resolutions` selects/passes `slug`; `_process_market_resolution(market_id, slug)`
  slug fallback + conditionId validation; new `_coerce_outcome_prices`; `json` import)

Created:
- projects/polymarket/crusaderbot/tests/test_candle_resolution.py

State:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- Full suite: **1740 passed, 1 skipped** (9 new candle-resolution cases). py_compile clean.
- Verified against live Gamma: `condition_ids` filters (count=1), `conditionId` ignored
  (count=20 incl garbage), candle resolvable by `/events?slug=` with `closed:true` +
  string `outcomePrices`.
- New tests cover: get_market param + conditionId validation (match/mismatch/empty),
  get_event_market_by_slug parsing, outcome coercion (string/list/garbage),
  winner-enqueue + loser-settle + `resolved=TRUE` via slug fallback, and
  conditionId-mismatch routing to pending (never mis-settle).
- Existing redeem tests (pending_settlement routing, hourly/instant workers) still green.

## 5. Known issues

- End-to-end settlement of real candle markets requires a Fly deploy + scheduler ticks;
  not exercised in-container (verified via direct Gamma probes + unit tests).
- `get_event_market_by_slug` is uncached (intentional — resolution needs the fresh
  `closed` flag); it adds one `/events` call per unresolved candle market per tick.
- Winners still route through the redeem queue before the position flips to closed
  (existing design); the position shows settled after the redeem worker runs.

## 6. What is next

- WARP•SENTINEL MAJOR validation (settlement/capital path + get_market correctness).
- Post-merge + Fly redeploy: confirm via Supabase MCP (project ykyagjdeqcgcktnpdhes) that
  the 5 stuck positions settle (`status='closed'`, `exit_reason` resolution_win/loss) and
  `markets.resolved` flips TRUE for past-due updown markets; watch a fresh Close Sweep
  position open and then settle at its candle end time.
- Optional follow-up: a brief cache on `get_event_market_by_slug` keyed on the closed
  flag, if `/events` call volume becomes a concern at scale.
