# WARP-77 Phase 1.2 — Real-CLOB data cutover + feed heartbeat

- Role: WARP•R00T
- Validation Tier: MAJOR (scheduler job + read-path instrumentation) — additive,
  dormant under `USE_PYSDK_CLOB`, fail-soft. Merged under WARP•R00T authority.
- Claim Level: NARROW INTEGRATION
- Validation Target: a real-CLOB-data feed heartbeat that pages the operator +
  Sentry if the market-data feed dies after the cutover; documented cutover steps.
- Not in Scope: flipping `USE_PYSDK_CLOB` (operator `fly secrets set`), the deploy,
  the 24h live observation, and any order-path behavior change.
- Branch: `WARP/root-clob-data-heartbeat`

---

## 1. What was built

A real-CLOB-data feed heartbeat (the WARP-77 Phase 1.2 monitoring deliverable),
plus this cutover runbook:

- **`monitoring/clob_heartbeat.py`** — tracks the freshness of the unauthenticated
  CLOB data feed. `mark_clob_read_ok()` stamps a timestamp on every successful
  `MarketDataClient` read; `check_clob_feed_and_alert()` pages the operator
  (Telegram) + Sentry, **once per down↔up transition** (latched, auto-resume),
  when the newest read is older than `CLOB_DATA_FEED_TIMEOUT_SEC`. Mirrors the
  WARP-76 H3 RTDS oracle feed-loss fail-safe.
- **`integrations/clob/market_data.py`** — `MarketDataClient._get` (the single
  funnel for `/book`, `/midpoint`, `/price`, `/markets`, …) marks a successful
  read via a lazy, fail-soft helper.
- **`scheduler.py`** — `clob_data_feed_heartbeat_job` registered on an interval
  (`CLOB_DATA_FEED_CHECK_INTERVAL_SEC`, default 60s), gated by
  `CLOB_DATA_FEED_HEARTBEAT_ENABLED`.
- **`config.py`** — `CLOB_DATA_FEED_TIMEOUT_SEC=180`,
  `CLOB_DATA_FEED_CHECK_INTERVAL_SEC=60`, `CLOB_DATA_FEED_HEARTBEAT_ENABLED=True`.

### Dormancy (cannot page in current prod)
The alarm **arms only when `USE_PYSDK_CLOB` is true**. On the legacy adapter
(current prod) `check_clob_feed_and_alert` returns immediately — proven by
`test_dormant_when_pysdk_off` (very stale feed, `USE_PYSDK_CLOB=False` → zero
pages, zero Sentry). `mark_clob_read_ok` is a cheap timestamp set that runs in
both modes with no side effects. Every path is fail-soft.

## 2. Cutover — what the operator flips (NOT a CC action)

The real-CLOB data/order backend is `PolymarketSdkClient` (CLOB v2), already
merged (#1638) and proven at the broker boundary by the WARP-74 staging proof
(true 8/8, all 5 reconcile cases GREEN from Fly nrt, `allow_fills=false`).

| Secret / env | Value | Effect |
|---|---|---|
| `USE_PYSDK_CLOB` | `true` | Switches the **authenticated order client** to CLOB v2 `PolymarketSdkClient`; **arms this heartbeat**. |
| `ENABLE_LIVE_TRADING` | stays `false` | LIVE capital path stays dormant (paper-on-real-data). |
| `ALLOW_FILLS` / `allow_fills` | stays `false` | No real USDC fills. |

Note: `MarketDataClient` (the public read feed the strategy consumes) is used in
BOTH modes — `USE_PYSDK_CLOB` only switches the signed order client. So the
heartbeat's read-freshness signal exists pre- and post-cutover; the **alarm** is
the part gated to arm at cutover.

Operator step: `fly secrets set USE_PYSDK_CLOB=true` → redeploy (CD).

## 3. Reader readiness (CLOB v2)

Verified by the WARP-74 staging proof chain (see PROJECT_STATE): on the pysdk
backend from Fly nrt, all five reconcile cases pass — order build/sign/POST
accepted, `get_open_orders` (owner-scoped + page-flattened + shape-mapped) returns
the resting order, kill-switch `cancel_all_orders` cancels it, post-kill poll
confirms gone. Price/orderbook reads go through the unauthenticated
`MarketDataClient` (unchanged by the cutover). No reader change was required here.

## 4. What is working

- Heartbeat staleness math, dormancy, and latched once-per-transition page+Sentry
  validated by `tests/test_warp77_clob_heartbeat.py` (5 hermetic tests) + an
  isolated harness; `py_compile` clean on all touched files.
- Zero behavior change in current prod (alarm dormant; mark is a no-op timestamp).

## 5. Known issues

- The 180s default `CLOB_DATA_FEED_TIMEOUT_SEC` is a starting point — tune it
  during the 24h post-cutover observation against real read cadence to avoid
  false pages / slow detection. `CLOB_DATA_FEED_HEARTBEAT_ENABLED=false`
  unregisters the job without code change if needed.
- The heartbeat observes the **data** feed (MarketDataClient), not the signed
  order backend; order-path health is covered by the WARP-74 reconciler.

## 6. What is next

- Operator: `fly secrets set USE_PYSDK_CLOB=true` + redeploy → 24h observation;
  document any drift / latency surprises; tune the timeout.
- Provenance (Phase 1.4, merged #1655) then accrues `paper_real` rows for WARP-78
  Phase 1 to filter on.

- Suggested Next Step: operator runs the cutover in a low-traffic window; after 24h
  clean observation, WARP-78 Phase 1 (Volatility/Momentum shadow on real data) can
  begin once CMD approves the Phase 0 findings.
