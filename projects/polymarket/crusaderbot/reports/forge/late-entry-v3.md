# WARP•FORGE Report — Late Entry V3

- Validation Tier: MAJOR
- Claim Level: NARROW INTEGRATION
- Validation Target: the late_entry_v3 domain strategy (entry gates + sizing handoff + flip-stop exit), its wiring as the Close Sweep engine, the exit-watcher per-strategy dispatch, the positions.strategy_type persistence, and the removal of the "Trade Blocked" Telegram notification.
- Not in Scope: live-trading execution path beyond the live.py strategy_type parity write (guards untouched); renaming/removing the expiration_timing lib strategy itself (only its close_sweep routing changed); other missing lib engines (trend_breakout/pair_arb/ensemble/value_investor/whale_tracking); Fly token rotation (ops, separate).
- Suggested Next Step: WARP•SENTINEL MAJOR validation, then Fly redeploy + live paper verification via Supabase MCP (project ykyagjdeqcgcktnpdhes).

---

## 1. What was built

Late Entry V3 — the real Close Sweep edge (ref github.com/bayuewalker/polybot_4coin
src/strategy.py) — implemented as a new **domain** strategy and made the sole engine
behind the `close_sweep` preset, replacing the placeholder `expiration_timing` lib
strategy.

The strategy enters only in the final 240 seconds of a live crypto up/down candle
(BTC/ETH/SOL/BNB, 5m/15m), buys the side the CLOB already prices as the likely winner
(higher ask), and exits if the favored price flips down. Position sizing flows through
the existing WARP risk gate (fractional Kelly + caps) rather than fixed contracts.

Two runtime gaps that previously made a faithful flip-stop impossible were closed:
- `positions.strategy_type` was written to `orders` but not to `positions` (NULL) —
  now persisted on both paper and live opens.
- The exit watcher used `default_strategy_evaluator`, a no-op that always returned
  False, so per-strategy `evaluate_exit()` hooks never ran — now a registry-backed
  dispatcher routes each position to its owning strategy by `strategy_type`.

Also (owner request, screenshot): the noisy "⚠️ Trade Blocked" Telegram notification
was removed. It only ever fired for `insufficient_liquidity` / `market_impact_cap`,
which is routine on thin candle markets; rejections remain recorded in
`scan_runs.rejection_breakdown` telemetry.

## 2. Current system architecture

Pipeline (unchanged): DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING.

Entry (STRATEGY): `LateEntryV3Strategy.scan(market_filters, user_context)`
1. `pm.get_crypto_window_markets(timeframe or "5m", assets)` — live candle window.
2. `is_short_crypto_market(m, timeframe, assets)` gate (asset whitelist + 5m/15m class).
3. Entry window: seconds-to-close from `endDate`/`endDateIso` (fallback: slug
   `{coin}-updown-{tf}-{slot}` -> `slot + step`); require `0 < secs <= 240`.
4. Read YES/NO best asks via `asyncio.gather(pm.get_book(yes_tok), pm.get_book(no_tok))`.
5. `favored = YES if yes_ask > no_ask else NO`; gates: `ask_diff >= 0.30`,
   `0 < (yes_ask+no_ask) <= 1.05`, `fav_price < 0.93`.
6. Emit `SignalCandidate(side=favored, suggested_size_usdc=balance*alloc*0.04 clamped,
   strategy_name="late_entry_v3", metadata={asks,spread,secs,...})`.

Sizing (RISK): the existing `domain/risk/gate.py:evaluate` consumes
`proposed_size_usdc` and applies fractional Kelly (0.25 cap) + per-profile position
caps. `late_entry_v3` is allow-listed in `STRATEGY_AVAILABILITY` so gate step 4 does
not reject it.

Exit (EXECUTION/MONITORING): `exit_watcher.run_once` (scheduler.py:541) fetches open
positions (now carrying `strategy_type`), fetches the live favored-side price, then
`evaluate()` checks force-close -> TP -> SL -> **strategy hook** -> horizon. The
strategy hook is now `registry_strategy_evaluator(position, current_price)`, which
looks up the owning strategy in `StrategyRegistry` by `strategy_type` and calls its
`evaluate_exit({... "current_price": cur})`. `LateEntryV3Strategy.evaluate_exit`
returns a `strategy_exit` when the favored side's live price `<= 0.48` (flip-stop).
Unattributed / unregistered `strategy_type` falls back to no-op (hold).

Routing: `signal_scan_job._PRESET_ALLOWED["close_sweep"] = {late_entry_v3}`; a
Phase-B2 block invokes the registered domain strategy per user (mirrors the
confluence_scalper block); the crypto-window upsert already runs for `close_sweep` so
candidates resolve in `_load_market`.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py
- projects/polymarket/crusaderbot/tests/test_late_entry_v3.py

Modified — strategy registration / availability:
- projects/polymarket/crusaderbot/domain/strategy/strategies/__init__.py
- projects/polymarket/crusaderbot/domain/strategy/registry.py
- projects/polymarket/crusaderbot/domain/risk/constants.py

Modified — scan-loop routing:
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py

Modified — exit path + strategy_type persistence:
- projects/polymarket/crusaderbot/domain/execution/exit_watcher.py
- projects/polymarket/crusaderbot/domain/positions/registry.py
- projects/polymarket/crusaderbot/domain/execution/paper.py
- projects/polymarket/crusaderbot/domain/execution/live.py

Modified — "Trade Blocked" notification removal:
- projects/polymarket/crusaderbot/services/trade_engine/engine.py
- projects/polymarket/crusaderbot/services/notification_service.py

Modified — tests:
- projects/polymarket/crusaderbot/tests/test_exit_watcher.py (evaluator signature + 2 dispatch cases)
- projects/polymarket/crusaderbot/tests/test_pipeline_runtime_hardening.py (assert trade.blocked suppressed)

State:
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- Full backend suite: 1731 passed, 1 skipped (includes 16 new test_late_entry_v3 cases,
  2 new exit_watcher registry-dispatch cases, and the inverted trade.blocked suppression
  test). py_compile clean on all 11 changed production files.
- Strategy contract + registry bootstrap + STRATEGY_AVAILABILITY membership verified.
- Entry gates verified (favored side selection; ask-diff / spread / favored-price /
  entry-window rejects; empty-book + blacklist + fetch-error safety -> []).
- Flip-stop verified at the unit level AND end-to-end through `exit_watcher.evaluate`
  (registry dispatch fires `strategy_exit` at favored price <= 0.48, after TP/SL).
- Sizing delegated to the gate (suggested $ size only; no fixed contracts).
- trade.blocked is no longer emitted on liquidity/impact rejection.

## 5. Known issues

- Live-runtime proof (real candidates -> position with strategy_type='late_entry_v3' ->
  flip-stop close) requires a Fly deploy + scheduler ticks; not exercised in-container.
- Confidence is a simple monotonic map of `ask_diff` (clamped to [0,1]); adequate for
  ranking/sorting but not a calibrated probability.
- Candle markets remain thin: step_11 (insufficient_liquidity) will still reject many
  candidates at the gate — expected; only the user-facing notification was removed.
- The other domain/lib engines still absent from STRATEGY_AVAILABILITY (out of scope).

## 6. What is next

- WARP•SENTINEL MAJOR validation (new position-opening strategy + exit-core dispatch).
- On approval + Fly redeploy: verify via Supabase MCP (project ykyagjdeqcgcktnpdhes) that
  a scan tick yields late_entry_v3 candidates in scan_runs (no step_4_unknown_strategy)
  and a positions row with strategy_type='late_entry_v3' on the favored side; confirm a
  close_sweep position can exit with exit_reason='strategy_exit' at favored price <=0.48.
- Optional follow-ups (separate lanes): calibrated confidence/edge for late_entry_v3;
  decide whether market_impact rejections deserve any (rate-limited) operator surfacing.
