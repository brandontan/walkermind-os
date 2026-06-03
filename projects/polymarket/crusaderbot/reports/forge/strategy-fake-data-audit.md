# WARP•R00T — Full active-strategy audit + kill fabricated trading-path prices

Branch: WARP/ROOT/kill-fabricated-prices
Trigger: owner — "full audit, check all active strategies work AND no more fake
data." Follows the weather (#1595), playbook (#1596) and SL-cap (#1599) lanes.
Date: 2026-06-04 Asia/Jakarta

## 0. Scope — every registered/active strategy audited

late_entry_v3 (crypto candle: close_sweep / safe_close / flip_hunter / candle_auto),
playbook (sports), weather, copy_trade (two live paths: legacy scan + monitor),
signal_following, and complete_set_arb. Each data path traced end-to-end
(sourcing → price/liquidity → signal → fill) hunting for placeholder / synthetic
/ hardcoded values presented as real.

## 1. Findings (file:line, severity)

SYSTEMIC fabrication class — a hardcoded `0.50` price (and `50_000` liquidity)
substituted when the live source was absent, then traded/stored as if real:

- CRITICAL `services/signal_scan/signal_scan_job.py:1783` `_build_trade_signal` —
  final `else 0.5` fill when no live mark. Reachable for EVERY scan strategy when
  `get_live_market_price` returns None.
- HIGH `signal_scan_job.py` upserts `_upsert_crypto_window_markets` /
  `_upsert_sports_markets` / `_upsert_weather_markets` — stored `0.5/0.5` when
  Gamma omitted `outcomePrices`. LIVE PROD EVIDENCE (markets table, status=active):
  155 crypto + 400 Weather + ~125 empty-category + hundreds of sports-futures rows
  sitting at exactly `0.50/0.50`; `null_price=0` everywhere — the placeholder was
  polluting prod continuously.
- CRITICAL `services/copy_trade/monitor.py:_extract_price` — returned `0.5` when a
  leader trade carried no price; built directly into the mirrored TradeSignal with
  NO live re-fetch → fake entry + distorted PnL.
- HIGH `services/copy_trade/monitor.py:_extract_liquidity` — returned `50_000` when
  absent → a thin market masquerades as deep and bypasses the risk-gate liquidity
  floor.
- MEDIUM `domain/signal/copy_trade.py:78` (legacy scan path, scheduled
  `legacy_copy_trade_scan`) — `float(trade.get("price") or 0.5)` candidate seed.

PASS / benign (no change):
- `complete_set_arb` — trades ONLY on real two-sided CLOB book walks
  (`fillable_complete_set` over real ask ladders); 2% min-net-edge floor
  non-bypassable. Verdict: production-safe, no fabrication.
- signal_following `$10` size / `0.6` confidence defaults = operator-intent
  fallbacks (only when the operator omits the field); copy `min_trade_size 0.5` =
  a skip floor; close_sweep randomised `min_ask_diff` = intentional Kreo design.
  These are config defaults, not market-data fabrication — left as-is.

## 2. What was built (fixes — TRADING path made honest, never fabricate)

- `_build_trade_signal` now REQUIRES a live mark: when no `live_price_override`
  it raises (no cached-DB / 0.50 fallback) → caller skips. + a call-site guard in
  `_process_candidate` that skips with `scan_outcome reason=no_live_price` when
  `_live_fill_price` is None/out-of-band. (`_live_fill_price` = candidate metadata
  entry for late_entry_v3, else `get_live_market_price` for every other strategy.)
- Upserts store NULL (new `_opt_price` helper) instead of `0.5` when Gamma omits a
  price — stops the DB pollution at the source; NULL never trades (guarded above)
  and the display freshness guard shows "awaiting" not a fake 50/50. All
  `float(yes_price/no_price)` readers were verified NULL-safe before this change.
- copy_trade monitor: `_extract_price`/`_extract_liquidity` return None when
  absent; `_process_one` then sources the REAL live CLOB book via new
  `_live_book_mark_and_depth` (midpoint + two-sided USDC depth) and SKIPS the
  mirror entirely if there is no real interior two-sided mark — no 0.50, no 50k.
- legacy `domain/signal/copy_trade.py`: skip a leader trade with no real interior
  price (no 0.50 seed).

## 3. Files modified (full repo-root paths)

- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
  (_opt_price; upserts -> NULL; _build_trade_signal requires live mark;
  _process_candidate no_live_price skip)
- projects/polymarket/crusaderbot/services/copy_trade/monitor.py
  (_extract_price/_extract_liquidity -> Optional; _live_book_mark_and_depth;
  _process_one live-book resolve + skip; honest liquidity)
- projects/polymarket/crusaderbot/domain/signal/copy_trade.py (skip priceless leader)
- projects/polymarket/crusaderbot/tests/test_signal_scan_job.py
  (no_live_price skip + _build_trade_signal raise tests; happy-path tests now supply
  a live mark)
- projects/polymarket/crusaderbot/tests/test_fast_track_a.py
  (_build_trade_signal tests use live override; new no-live-price-raises test)
- projects/polymarket/crusaderbot/tests/test_copy_trade_no_fake_price.py (NEW)

## 4. What is working

- 1000+ tests pass across signal-scan / copy-trade / fast-track / strategy /
  exit / gate / market-feed; ruff + py_compile clean on all changed source.
- New regression tests pin the invariant: no candidate fills without a real live
  mark; copy mirrors only on a real two-sided book; extract helpers never
  fabricate; upserts store NULL not 0.50.
- complete_set_arb re-verified clean (no change needed).

## 5. Known issues

- Existing prod rows already stored at 0.50 remain until re-synced; the upsert now
  overwrites them with NULL (or the real price) on the next scan tick — they will
  drain naturally. No backfill migration in this lane (display freshness guard
  already suppresses stale rows; trading path ignores them).
- Honest-but-stricter copy liquidity: a leader market with no synced/live book is
  now SKIPPED rather than mirrored on fake 50k. Correct per "no fake data"; if it
  proves too strict operationally that is a tuning follow-up, not a regression.
- Live-validation pending on Fly paper: after deploy, `scan_runs` should show
  `no_live_price` skips replacing silent 0.50 fills, and the markets table should
  stop accumulating exact-0.50 rows.
- Env-only: `web3` / `poly_eip712_structs` absent in the dev sandbox (pre-existing,
  CI has them) — unrelated test-collection noise.

## 6. What is next

- WARP•SENTINEL (MAJOR — capital / realised-PnL / market-data path) or owner merge
  -> Fly redeploy -> paper-observe.
- Separately tracked (owner-gated): late_entry_v3 zero-opens persist
  (`filter_or_no_match`) — that is a gate-strictness / candle-window matter, not
  fake data, and is out of this lane's scope.

---

Validation Tier   : MAJOR (market-data / realised-PnL / capital path)
Claim Level       : FULL RUNTIME INTEGRATION (changes which prices any strategy fills on)
Validation Target : no strategy fills without a real live mark; copy mirrors only on
                    a real two-sided book; upserts store NULL not 0.50; complete_set
                    re-verified clean
Not in Scope      : late_entry_v3 zero-opens (gate/window); prod 0.50 backfill;
                    operator-intent defaults (size/confidence); risk gate / Kelly
Suggested Next    : WARP•SENTINEL / owner merge -> Fly -> paper-observe no_live_price
