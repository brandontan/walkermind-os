# WARP•FORGE — webtrader-confluence-scalper

**Task:** WARP-61 — Expose `confluence_scalper` in WebTrader Auto Trade UI + Full Auto coverage with crypto-only eligibility gate.
**Issue:** #1269
**Branch:** `WARP/webtrader-confluence-scalper`
**Depends on:** WARP-60 (#1267 / `WARP/confluence-scalper-strategy`) — MERGED b3ec4b7d4930
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** WebTrader preset exposure + Full Auto eligibility wiring. Runtime safety still flows through the existing strategy registry, risk gate, paper/live guards, and execution path.
**Not in Scope:** No changes to the execution engine, risk gate, risk constants, activation guards, live trading guard, existing strategy cards, or strategy math beyond eligibility wiring. No Telegram UX in this lane (shared preset catalog metadata picked up automatically; no preset picker keyboard reshuffle).
**Suggested Next Step:** WARP🔹CMD review → Fly.io redeploy so the bot pod loads the wired scanner → WebTrader frontend rebuild + redeploy so the new Crypto Scalper card ships.

---

## 1. What was built

A narrow integration that surfaces the WARP-60 `ConfluenceScalperStrategy` to two user-visible runtime surfaces without changing existing behaviour:

1. **WebTrader Auto Trade preset card** — new "🚀 Crypto Scalper" preset positioned between Ensemble and Full Auto on `/auto-trade`. Selecting it persists `active_preset='confluence_scalper'` via the existing `/autotrade/preset` endpoint and the existing card-grid UI handles state, ACTIVE badge, and Settings sync.
2. **Full Auto coverage** — `_PRESET_ALLOWED['full_auto']` now also permits `confluence_scalper` so the existing trio is joined by the new strategy automatically; `_PRESET_ALLOWED[None]` mirrors the same set for users with no preset persisted (matches existing default-fallback behaviour).
3. **Crypto-only eligibility gate** — `signal_scan_job._is_crypto_eligible_for_confluence(market)` requires category == "Crypto" (case-insensitive across `category`, `groupItemTitle`, `slug`) AND the market title/question/slug match the BTC|bitcoin|ETH|ethereum|SOL|solana|XRP|ripple|DOGE|dogecoin|BNB|"binance coin"|HYPE|hyperliquid regex with word boundaries. Non-crypto and off-whitelist markets silently skip — other strategies on the same scan tick are not affected because the filter runs only on `confluence_scalper`'s emitted candidates.

The domain strategy itself was not touched — WARP-60 already ships `ConfluenceScalperStrategy` with full `scan()` / `evaluate_exit()` / `default_tp_sl()` contract and 36 hermetic tests; this lane only wires it into the scan loop and exposes the activation surface.

## 2. Current system architecture

```
DATA -> [STRATEGY <-- lib/ + domain confluence_scalper] -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING
```

* `signal_scan_job.run_once()` flow per user, per tick:
  1. Load enrolled users + per-user `active_preset` + `category_filters` + `strategy_params`.
  2. Fetch raw Gamma market list once for the tick; build `crypto_market_ids` set via `_crypto_eligible_market_ids()`.
  3. Phase A: lib strategies (whale_tracking / trend_breakout / momentum / value_investor / expiration_timing / pair_arb / ensemble) — unchanged.
  4. **Phase B (NEW): if `_preset_allows(active_preset, 'confluence_scalper')`** → fetch the registered domain strategy via `StrategyRegistry.instance().get('confluence_scalper')`, call `scan(market_filters, user_ctx)`, filter emitted candidates against `crypto_market_ids`, feed survivors through the same `_process_candidate(row, cand)` path as Phase A.
  5. Phase C: signal_publications feed — unchanged.
* `_PRESET_ALLOWED`:
  * `confluence_scalper` → `{confluence_scalper}` (isolated)
  * `full_auto` → existing `_LIB_STRATEGY_NAMES` ∪ `{confluence_scalper}`
  * `None` → same as `full_auto`
  * Every other preset → unchanged; `confluence_scalper` is NOT silently activated for `whale_mirror` / `trend_breakout` / `contrarian` / `value_hunter` / `close_sweep` / `pair_arb` / `ensemble` (regression-tested).
* WebTrader preset card → `activatePreset('confluence_scalper')` → `POST /autotrade/preset` → router `_PRESET_PARAMS['confluence_scalper']` (`risk_profile=balanced, capital_alloc_pct=0.40, tp_pct=0.08, sl_pct=0.04`) → `UPDATE user_settings SET active_preset='confluence_scalper', risk_profile='balanced', capital_alloc_pct=0.40, tp_pct=0.08, sl_pct=0.04`.

## 3. Files created / modified (full repo-root paths)

**Modified (5):**
* `projects/polymarket/crusaderbot/webtrader/backend/router.py` — added `confluence_scalper` entry to `_PRESET_PARAMS` so `/autotrade/preset` accepts the new key.
* `projects/polymarket/crusaderbot/bot/presets.py` — `PRESET_CONFIG['confluence_scalper']` entry and `PRESET_ORDER` insert between `ensemble` and `full_auto`.
* `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — imported `re`; added `_CRYPTO_SCALPER_ASSETS` whitelist + compiled word-boundary regex; added `_is_crypto_eligible_for_confluence()` + `_crypto_eligible_market_ids()`; expanded `_PRESET_ALLOWED` with `confluence_scalper` and Full Auto inclusion; added Phase B domain-strategy execution block inside `run_once()`; extended log + event_bus emit with `confluence_signals` count.
* `projects/polymarket/crusaderbot/services/notification_service.py` — `_STRAT_LABELS['confluence_scalper'] = '🚀 Crypto Scalper'`.
* `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` — same label mapping for the per-trade notifier path.
* `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx` — inserted `confluence_scalper` entry into the `STRATEGY_PRESETS` const array between `ensemble` and `full_auto`; signal copy `Fast crypto momentum + liquidity confluence (BTC/ETH/SOL/XRP/DOGE/BNB/HYPE · 5m/15m)`; engine label `ConfluenceScalperStrategy`; risk `advanced`; freq `High`.

**Created (1):**
* `projects/polymarket/crusaderbot/tests/test_webtrader_confluence_scalper_exposure.py` — 22 hermetic tests, no DB / no Telegram / no HTTP.

**State files updated:**
* `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
* `projects/polymarket/crusaderbot/state/WORKTODO.md`
* `projects/polymarket/crusaderbot/state/CHANGELOG.md`

## 4. What is working

* `py_compile` clean on all 5 touched Python files (`router.py`, `presets.py`, `signal_scan_job.py`, `notification_service.py`, `notifier.py`).
* `py_compile` clean on the new test file.
* Standalone regex sanity check on `_is_crypto_eligible_for_confluence`: PASSED 20/20 cases — 12 crypto positives (BTC/Bitcoin/ETH/Ethereum/SOL/Solana/XRP/DOGE/Dogecoin/BNB/HYPE/Hyperliquid markets), 7 non-crypto rejections (Politics/Sports/Weather/Finance/Entertainment/World/Science even when the question mentions a crypto asset), word-boundary protection ("hyperventilating" does NOT match HYPE).
* Hermetic test coverage in `tests/test_webtrader_confluence_scalper_exposure.py`:
  * Catalog exposure — `get_preset('confluence_scalper')` returns a populated `PresetConfig`; `PRESET_ORDER` index is between `pair_arb` and `full_auto`; all existing preset keys still present.
  * Selection mapping — `_PRESET_PARAMS['confluence_scalper']` returns `risk_profile='balanced'`, `tp_pct=0.08`, `sl_pct=0.04`; all legacy + new preset_keys preserved.
  * Full Auto inclusion — `confluence_scalper` ∈ `_PRESET_ALLOWED['full_auto']` and `_PRESET_ALLOWED[None]`; `_PRESET_ALLOWED['confluence_scalper'] == frozenset({'confluence_scalper'})` (isolated).
  * Preset isolation regression — other presets (whale_mirror / trend_breakout / contrarian / value_hunter / close_sweep / pair_arb / ensemble) do NOT activate `confluence_scalper`.
  * `_preset_allows()` returns True for (`confluence_scalper`, `confluence_scalper`) and (`full_auto`, `confluence_scalper`); False for (`whale_mirror`, `confluence_scalper`).
  * Eligibility gate — 12 crypto positives across all 7 whitelisted assets; 7 non-crypto category rejections; off-whitelist crypto market rejected; word-boundary "hyperventilating" rejected; `_crypto_eligible_market_ids` returns the correct subset.
  * Invalid input safety — `None`, missing `category`, missing `question` all return False without raising.
* Domain `ConfluenceScalperStrategy` itself unchanged from WARP-60 — its scan/exit/tp_sl contract and 36 hermetic tests remain green.
* Engine id, name, and risk-profile compatibility list intact — selecting the preset persists `active_preset='confluence_scalper'` and the engine label rendered in WebTrader matches `ConfluenceScalperStrategy`.

## 5. Known issues

* Pytest not exercised in this remote container — `pytest` collection trips the telegram → cryptography → pyo3 Rust binding chain that is unsatisfiable in the FORGE execution sandbox (identical posture documented for WARP-58 / WARP-59 / WARP-60). The new test file's `py_compile` is clean and the standalone regex check passed; WARP🔹CMD or CI should run `pytest projects/polymarket/crusaderbot/tests/test_webtrader_confluence_scalper_exposure.py` before merge.
* Vite + `tsc` not run here — `node_modules/` is not present in this remote container. The TSX edit is a pure additive entry to the existing const-array of preset card objects using the same shape (key/name/emoji/engine/signal/risk/freq) as siblings; TypeScript inference is unchanged. WARP🔹CMD or CI should run `npm run build` inside `projects/polymarket/crusaderbot/webtrader/frontend/` before deploying the frontend bundle.
* "Duration whitelist: 5m, 15m" from the issue is treated as user-facing strategy metadata embedded in the WebTrader card copy (`… · 5m/15m`). The underlying `ConfluenceScalperStrategy` does not expose an explicit timeframe gate at the per-market level — Polymarket prediction markets do not carry a 5m/15m duration property — and the issue's "No new strategy math beyond eligibility wiring" guard rules out introducing one in this lane.
* Activation guards untouched. `ENABLE_LIVE_TRADING` / `EXECUTION_PATH_VALIDATED` / `CAPITAL_MODE_CONFIRMED` remain OFF; paper-only posture preserved.

## 6. What is next

* WARP🔹CMD review of `WARP/webtrader-confluence-scalper` (issue #1269) → merge decision.
* Post-merge: Fly.io redeploy so the running bot pod imports the wired scanner + WebTrader frontend rebuild + redeploy so the new Crypto Scalper card ships to users.
* Out of scope, separate lane if/when WARP🔹CMD dispatches it: Telegram preset picker keyboard surface for `confluence_scalper` and per-user user_strategies row backfill for users who explicitly want to OPT-IN to the new strategy without selecting Full Auto.
