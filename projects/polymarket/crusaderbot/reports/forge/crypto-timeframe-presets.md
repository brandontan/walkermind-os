# WARP•FORGE Report — crypto-timeframe-presets

Branch: WARP/crypto-timeframe-presets
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION (code + unit/typecheck/build validation; full
live-runtime proof requires Fly deploy + migration 049 applied + scan ticks)
Validation Target: short-duration crypto timeframe (5m/15m) gating for
confluence_scalper + close_sweep, crypto category auto-lock, Ensemble→Smart Mix
rename, hide not-yet-valid web strategies.
Not in Scope: Kreo-style Oracle/Distance/Max-Spread/Sides/Trend knobs; timeframes
other than 5m/15m; renaming the `ensemble` DB key; whale_tracking functionality
fix; backend/telegram strategy-list changes (hide is web-only).
Suggested Next Step: WARP•SENTINEL validation (MAJOR — touches scan pipeline +
strategy market gating), then apply migration 049 to Supabase + Fly redeploy +
observe `None`-classified crypto markets in logs to tune the timeframe regex.

## 1. What was built

A short-duration crypto timeframe system for the two crypto-short presets,
modeled on (but simpler than) the Kreo Polymarket bot:

1. **Timeframe (5m / 15m)** — a new per-user setting. Selecting the Crypto
   Scalper or Close Sweep preset auto-applies a timeframe (default 5m) and the
   bot then trades only crypto markets whose candle interval matches.
2. **Crypto-only auto-lock** — activating either crypto-short preset forces the
   market category filter to Crypto only (server-side) and locks the category
   checkboxes in the web UI.
3. **Light per-timeframe tuning** ("filter + preset ringan") — confluence_scalper
   tightens its price band + drift floor per timeframe in-code; close_sweep gets
   per-timeframe `hours_before_*` + price band merged into its strategy_params.
4. **Ensemble → "Smart Mix"** rename (display only; DB key `ensemble` unchanged).
5. **Hide not-yet-valid web strategies** — removed `whale_mirror` (degraded:
   prob.trade api_client unavailable, DEFERRED) and the entire "Coming Soon"
   section (Logic Arb, Sentiment) from the WebTrader strategy grid.

## 2. Current system architecture

```
DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING
```

Timeframe flows: user_settings.selected_timeframe (mig 049)
  -> signal_scan_job._load_enrolled_users SELECT
  -> UserContext.selected_timeframe (confluence_scalper reads it)
  -> close_sweep: signal_scan_job pre-filters markets via is_short_crypto_market
Classification is centralized in domain/strategy/eligibility.py
(classify_crypto_timeframe + is_short_crypto_market), composing the existing
crypto asset whitelist with a keyword-first (duration-fallback) interval
classifier. Fail-closed: unclassifiable -> skip.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/migrations/049_strategy_timeframe.sql
- projects/polymarket/crusaderbot/tests/test_crypto_timeframe.py

Modified:
- projects/polymarket/crusaderbot/domain/strategy/eligibility.py (classifier + is_short_crypto_market)
- projects/polymarket/crusaderbot/domain/strategy/types.py (UserContext.selected_timeframe)
- projects/polymarket/crusaderbot/domain/strategy/strategies/confluence_scalper.py (timeframe gate + per-tf tuning)
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py (SELECT + ctx + close_sweep pre-filter)
- projects/polymarket/crusaderbot/services/signal_scan/lib_strategy_runner.py (endDate -> end_date_iso mapping fix)
- projects/polymarket/crusaderbot/webtrader/backend/schemas.py (selected_timeframe fields)
- projects/polymarket/crusaderbot/webtrader/backend/router.py (auto-lock + tf write + tf params merge)
- projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts (type + activatePreset)
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx (toggle, lock, hide, rename)
- projects/polymarket/crusaderbot/bot/presets.py (Smart Mix)
- projects/polymarket/crusaderbot/bot/messages.py (Smart Mix)
- projects/polymarket/crusaderbot/bot/handlers/onboarding.py (Smart Mix)
- projects/polymarket/crusaderbot/tests/test_confluence_scalper.py (fixture short-duration default)

## 4. What is working

- 264 backend tests green: test_crypto_timeframe (13 new) + test_confluence_scalper
  (incl. updated fixture) + test_webtrader_confluence_scalper_exposure +
  test_lib_strategy_loading + test_signal_scan_job + test_preset_system +
  test_market_signal_scanner (160 in the targeted scan/preset run; 104 in the
  scalper/classifier/loading run).
- Frontend: `tsc --noEmit` clean; `npm run build` succeeds.
- py_compile clean on all 10 modified Python files.

## 5. Known issues

- **Timeframe detection reliability (primary risk):** no structured 5m/15m field
  on Gamma markets; classification depends on slug/question keyword regex
  (authoritative) + duration fallback (corroborative). Fail-closed mitigates
  mistrades; recommend logging crypto markets that classify as None to tune.
- Existing confluence_scalper users with NULL selected_timeframe now trade only
  5m/15m crypto markets (timeframe=None accepts any classified bucket) — narrower
  than before, by design.
- whale_tracking remains degraded (out of scope); only hidden from the web grid.

## 5a. Follow-up fix (WARP/crypto-timeframe-detection-fix)

Live test on deploy (Close Sweep @ 5m) emitted 0 candidates: real Polymarket
candle markets carry `category` = their own series slug (e.g.
`btc-updown-5m-1779249900`) with no literal "crypto", so the old
`is_confluence_scalper_eligible` category gate inside `is_short_crypto_market`
rejected every real 5m/15m market. Fixed `is_short_crypto_market` to establish
crypto-ness via the asset-ticker whitelist (BTC/ETH/SOL/...) + a detected
5m/15m interval instead of the literal category — the timeframe gate supplies
the precision. The classifier regex already matched the `-5m-`/`-15m-` slug
tokens. Added real-slug regression tests (btc-updown-5m/15m, eth-updown-5m,
eth daily skip); updated the non-crypto scan test to assert via the timeframe
gate. 146 tests green.

## 6. What is next

- WARP•SENTINEL MAJOR validation.
- Apply migration 049 + Fly redeploy; observe classification logs and tune regex
  against real crypto-candle slugs.
