# WARP•R00T — Weather real-CLOB price sourcing (kill the 0.50 fake)

Branch: WARP/ROOT/strategy-real-clob-sourcing
Trigger: owner report — weather + playbook open ZERO positions all day (paper).
Mandate: "strategy work realtime, no fake data, no cosmetic, ready 100% LIVE/PAPER."
Date: 2026-06-04 Asia/Jakarta

## 0. Diagnosis (live-evidence, prod Supabase + Polymarket APIs)

Root-caused with the live prod DB (`scan_runs` telemetry) + live Gamma/CLOB:

- Every full scan: `markets_seen≈1154`, `markets_eligible=0`, `candidates_emitted=0`;
  `zero_reason_breakdown` = `weather:filter_or_no_match` (+ playbook + late_entry_v3).
- prod `markets`: 490 active Weather rows, ALL stored `yes_price=0.50 / no_price=0.50 /
  liquidity_usdc=0` — the strategy's `max_price ≤ 0.45` gate rejects every one.
- Live CLOB books prove the markets are NOT all dead: e.g. Jeddah-37°C token has a real
  two-sided book `bid 0.42 / ask 0.43`; Gamma "by liquidity" lists ~11 temperature
  markets up to ~$10k. The book exists — **we just never read it.**
- Cause: `fetch_weather_markets` ordered Gamma by `startDate` (newest = unpriced) and read
  `outcomePrices`, defaulting to `["0.5","0.5"]` when absent — so a real `0.42/0.43` market
  was stored as `0.50` and rejected. **Fake placeholder data, exactly what the owner flagged.**

(Playbook + weather-thinness findings recorded in PROJECT_STATE [KNOWN ISSUES]; playbook
sourcing/window/category is the next lane. This lane fixes weather pricing only.)

## 1. What was built

`fetch_weather_markets` now prices each market from REAL data, never a placeholder:
- Gamma query ordered by `liquidity` (was `startDate`) so liquid, priced markets surface.
- New pure helpers: `_book_quote` (mid/spread/two-sided-depth from a CLOB `/book`),
  `_parse_gamma_outcomes` (real Gamma price, or `None` for the 0.50/0.50 sentinel),
  `_extract_yes_token`.
- New `_build_weather_markets(data, city, book_fetcher)` (HTTP-free except the injected
  book fetcher → hermetically testable): uses the real Gamma price when present; otherwise
  fetches the live CLOB midpoint via `book_fetcher` (default
  `integrations.polymarket.get_book`, bounded to `_MAX_BOOK_FETCH=40`, fail-soft). A market
  with no real two-sided book is **SKIPPED — never emitted at a fabricated 0.50.**

## 2. Current system architecture (relevant slice)

```
DATA: strategies/weather/market.fetch_weather_markets
        Gamma /markets (order=liquidity)
        -> _build_weather_markets:
             real Gamma price  ─┐
             else CLOB midpoint ─┼─> WeatherMarket(yes_price = REAL)
             else (no book)     ─┘   -> SKIP (no 0.50 fake)
STRATEGY: domain/strategy/strategies/weather.evaluate
        gates on REAL price now: max_price≤0.45 / max_spread / min_volume / EV / hours
RISK GATE: unchanged ($10k liquidity + impact still apply — thin weather still rejected)
```

No change to risk constants, gates, Kelly, or `ENABLE_LIVE_TRADING`. Thin/illiquid
weather markets still (correctly) fail the risk gate — the fix only stops us LYING about
the price so the genuinely-priced ones can be evaluated honestly.

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/strategies/weather/market.py (real-CLOB pricing;
  `_book_quote` / `_parse_gamma_outcomes` / `_extract_yes_token` / `_build_weather_markets`;
  order=liquidity; `book_fetcher` injection; skip-not-fabricate)

Created:
- projects/polymarket/crusaderbot/tests/test_weather_clob_sourcing.py
- projects/polymarket/crusaderbot/reports/forge/weather-real-clob-sourcing.md (this report)

## 4. What is working

- 113 tests pass (7 new weather-CLOB + test_market_feed_preset + test_signal_scan_job);
  31 weather-suite tests green; ruff + py_compile clean.
- New tests prove the core invariant: **no WeatherMarket is ever emitted at 0.50** — real
  Gamma price preserved, placeholder priced from the CLOB book, unpriceable markets skipped.
- `book_fetcher` injection keeps all three production callers unchanged (default = real
  `get_book`) and the logic hermetic.

## 5. Known issues

- LIVE-VALIDATION PENDING: hermetic tests + live API inspection done, but the full scan was
  not run end-to-end here (dev has no DATABASE_URL). Confirm on Fly paper post-deploy that
  `scan_runs.zero_reason_breakdown` shows weather pricing real values and weather positions
  open when a genuinely liquid+priced weather market clears the gates.
- Weather markets on Polymarket are THIN — most are one-sided / sub-$10k liquidity, so even
  with real prices only a handful will clear the $10k risk-gate floor at any time. This is
  correct (honest) behaviour, not a bug: weather will trade only when a real, liquid, priced
  market exists. Expect low frequency.
- 40-book-per-scan cap bounds CLOB reads; if a scan needs more, raise `_MAX_BOOK_FETCH`.

## 6. What is next

- WARP•SENTINEL (MAJOR, money-path market sourcing) or owner merge -> Fly redeploy ->
  paper-observe weather pricing/opens.
- NEXT LANE (owner-sequenced): playbook sourcing+window+category — single (0,72h] window,
  game-event sourcing (today's individual games, not season futures), broadened sports
  category match. Trades existing bands (Closing-Edge ≤2h + Sharp-Money ≥24h); the 2–24h
  mid-band stays uncovered until Injury/Public feeds are enabled (needs ODDS_API_KEY +
  resolver — owner inputs).

---

Validation Tier   : MAJOR (strategy market sourcing — money path)
Claim Level       : FULL RUNTIME INTEGRATION (changes what weather feeds the gates)
Validation Target : fetch_weather_markets emits real CLOB/Gamma prices, never 0.50;
                    order=liquidity; fail-soft; bounded book reads
Not in Scope      : playbook (next lane); risk gates; $10k liquidity floor; candle freshness
Suggested Next    : WARP•SENTINEL / owner merge -> Fly -> paper-observe -> playbook lane
