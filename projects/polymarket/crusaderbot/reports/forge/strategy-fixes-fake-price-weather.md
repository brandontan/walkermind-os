# WARP•FORGE Report — strategy-fixes-fake-price-weather

**Branch:** `WARP/ROOT/strategy-fixes-fake-price-weather`
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Three independent paper-mode regressions blocking observable trade flow — fake-price 0.50 leak into the markets table + signal evaluator; weather strategy hard-disabled at the flag; copy-trade rejected at risk-gate step 2.
**Not in Scope:** Live-trading guard flip (`ENABLE_LIVE_TRADING`, `USE_REAL_CLOB`, etc. stay `'false'` in `fly.toml`); SENTINEL audit (tier is STANDARD); demo-feed flag verification (separate lane); copy-trade `copy_direction='buys_only'` default review (separate lane).

---

## 1. What was built

Owner reported in paper testing: "Strategy weather dan copy trade tp gk ada open trade" and "masih ada fake data yg kesangkut". Three independent root causes were diagnosed via three parallel investigation passes (weather signal path, copy-trade execution path, fake-data hunt across runtime code). Each root cause was fixed independently in this single branch.

**Fix #1 — Kill the 0.50 fake-price fabrication (CRITICAL)**
`jobs/market_sync.py` was calling `_safe_float(..., default=0.50)` for both `yes_price` and `no_price` when Polymarket Gamma `outcomePrices` was absent or unparseable. The fabricated 0.50/0.50 then propagated permanently into the `markets` table via `INSERT ... ON CONFLICT DO UPDATE`, and `services/signal_scan/signal_scan_job.py:1003` read it back as `_yes_p = float(market.get("yes_price") or 0.5)` into its fast-topup fallback. Net effect: any market with missing CLOB data was treated as a 50/50 fair coin, poisoning edge/confidence/sizing math and silently steering paper-mode trades. Fixed by replacing both fabrications with explicit skips — markets with no real prices are not upserted at all; topup with no real price is logged with `reason='no_market_price'` and aborted.

**Fix #2 — Activate the weather strategy and surface its disabled state in telemetry**
`config.py:132` declared `WEATHER_STRATEGY_ENABLED: bool = False`. The runtime check at `domain/strategy/strategies/weather.py:86-89` returns `[]` immediately if the flag is unset, but the telemetry call at `services/signal_scan/signal_scan_job.py:2841` was emitting `zero_reason="filter_or_no_match"` either way, hiding the real cause behind a false filter signal. Fixed by setting `WEATHER_STRATEGY_ENABLED='true'` in `fly.toml` (production env var, not a live-trading guard), adding `min_size_usdc: 0.10` to `strategies/weather/weather_config.json` so small paper bankrolls do not get every candidate dropped at the size gate (`domain/strategy/strategies/weather.py:264`, hardcoded default was 0.50), and gating the scan call on the flag so the scanner can emit `zero_reason='strategy_disabled'` when off.

**Fix #3 — Per-task opt-in bypass for copy-trade at risk gate step 2**
`domain/risk/gate.py:267` was: `if ctx.paused or not ctx.auto_trade_on: return GateResult(False, "auto_trade_off_or_paused", 2)`. `users.auto_trade_on` defaults FALSE (`migrations/001_init.sql:12`, reinforced by `migrations/052_new_user_defaults.sql:13` with the comment "user must explicitly enable"). Only the Telegram `/live_checklist` activation flow flips it. The "start copying" flow at `bot/handlers/mvp/copy_wallet.py:do_start_copying` and the full handler at `bot/handlers/copy_trade.py` insert active `copy_trade_tasks` rows but never touch `auto_trade_on`. Net effect: every copy-trade candidate was hard-rejected at step 2 with `auto_trade_off_or_paused`, then `monitor.py:416` marked it processed so it never retried — the exact "no open trade, no error" symptom. Fix: added `GateContext.bypass_auto_trade_check: bool = False`. Copy-trade `services/copy_trade/monitor.py:319` sets it `True` because `copy_trade_tasks.status='active'` IS the explicit per-task opt-in. `TradeSignal` and `TradeEngine._build_gate_context` were threaded with the new flag. Critically, `ctx.paused` is still hard-honoured by a separate check (the global `/pause` still stops everything), and all 13 other risk gate steps (size caps, daily loss, drawdown, concurrency, liquidity, kill switch, live guards) still apply.

## 2. Current system architecture

```
Polymarket Gamma API
        │
        ▼
jobs/market_sync.py
   │  (FIXED — skip markets without real prices instead of writing 0.50)
   ▼
markets table  (canonical price source)
        │
        ▼
services/signal_scan/signal_scan_job.py
   │  fast_topup fallback FIXED — skip topup if market has no real price
   │  weather scan FIXED — explicit disabled-flag check + telemetry reason
   ▼
SignalCandidate
        │
        ▼
TradeEngine._build_gate_context(signal)
   │  (signal.bypass_auto_trade_check → ctx.bypass_auto_trade_check)
   ▼
domain/risk/gate.py
   │  step 1: kill switch          (unchanged)
   │  step 2: paused → reject       (always honoured)
   │  step 2: auto_trade_on off → reject UNLESS bypass_auto_trade_check
   │  steps 3-15: unchanged          (all caps + live guards still enforce)
   ▼
Execution (paper or live, per chosen_mode)


Copy-trade specific path:
services/copy_trade/scheduler.py (60s, unconditional)
        │
        ▼
services/copy_trade/monitor.py.run_once
   │  loads copy_trade_tasks WHERE status='active'  (per-task opt-in)
   │  fetches leader trades from Polymarket Data API (real)
   ▼
TradeSignal(..., bypass_auto_trade_check=True)
        │
        ▼
TradeEngine.execute → gate (now passes step 2 by task opt-in)
```

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/jobs/market_sync.py` — drop `default=0.50` fallback; skip upsert when either side has no real price.
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — fast_topup fallback no longer fabricates 0.5 from `market_row`; weather scan now checks `WEATHER_STRATEGY_ENABLED` upfront and emits accurate `zero_reason` telemetry (`strategy_disabled` vs `filter_or_no_match`).
- `projects/polymarket/crusaderbot/strategies/weather/weather_config.json` — add `min_size_usdc: 0.10` (paper-bankroll friendly).
- `projects/polymarket/crusaderbot/fly.toml` — add `WEATHER_STRATEGY_ENABLED='true'` (non-live-trading env flag).
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — add `GateContext.bypass_auto_trade_check` field; refactor step 2 into separate `paused` and `auto_trade_on` checks; bypass applies only to the latter.
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py` — add `TradeSignal.bypass_auto_trade_check` field; thread through `_build_gate_context`.
- `projects/polymarket/crusaderbot/services/copy_trade/monitor.py` — set `bypass_auto_trade_check=True` when constructing the copy-trade `TradeSignal`.

State files (this report):
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Last Updated, Status, [COMPLETED], [NEXT PRIORITY] surgical-edited per CLAUDE.md SURGICAL EDIT RULE.
- `projects/polymarket/crusaderbot/reports/forge/strategy-fixes-fake-price-weather.md` — this file (new).

Created: none beyond this report.

Deleted: none.

## 4. What is working

- `python -c "import ast; ..."` syntax check clean across all 4 modified Python files.
- `python -c "import json; ..."` clean on `weather_config.json`.
- `pytest projects/polymarket/crusaderbot/tests/test_fast_track_a.py` — 49 passed, 0 failed (covers risk gate step 2 rejection paths; the existing `auto_trade_off_or_paused` reason string is preserved so test expectations still match).
- `pytest projects/polymarket/crusaderbot/tests/ -k "gate or copy_trade or trade_engine or risk or weather or market_sync"` — 441 passed, 0 failed.
- The `auto_trade_off_or_paused` `GateResult.reason` string is unchanged (tests assert on it); internal `_log` reason strings are now more specific (`paused` vs `auto_trade_off`) for risk_log audit clarity.

## 5. Known issues

- One bonus discovery from the fake-data hunt is intentionally OUT OF SCOPE for this lane: `jobs/market_signal_scanner.py:395-396` honours `SCANNER_DEMO_FEED_ENABLED` which, if mistakenly left `true` in production, would publish demo markets to the live signal feed with `is_demo=FALSE`. Owner explicitly skipped the demo-feed verification when selecting fix scope. Recommend a separate one-line audit before LIVE flip: confirm `SCANNER_DEMO_FEED_ENABLED` is not set in Fly secrets (defaults to False at `config.py`).
- Copy-trade `copy_direction='buys_only'` is the insert default at `bot/handlers/mvp/copy_wallet.py:195` and `bot/handlers/copy_trade.py`. If a followed leader's recent activity is dominated by SELLs, copy-trade still emits zero candidates after this fix because step 245 of the monitor drops every leader SELL. Worth a UX review in a follow-up lane (offer `both` as the default for paper testing).
- Per-strategy `min_size_usdc` is hardcoded in `domain/strategy/strategies/weather.py:113` if `weather_config.json` doesn't supply it. This branch adds the JSON key; long-term the default should also drop to 0.10 in code for parity with paper defaults.

## 6. What is next

- WARP🔹CMD review + merge of this branch (STANDARD, no SENTINEL required per tier rules).
- Fly deploy to activate weather strategy + copy-trade routing in production paper mode.
- Owner re-test weather + copy-trade in Telegram bot: confirm at least one weather candidate emits and at least one leader-wallet trade fires a copy-trade signal that reaches `paper.execute`.
- Then continue strategy-perfection work in paper mode per owner's "benerin smpe sempurna dl di paper trade" direction.

**Suggested Next Step:** Owner picks the next strategy shortcoming to fix (e.g. flip_hunter underdog-mode behaviour, candle market edge calibration, copy-trade `copy_direction` default), and gives WARP•FORGE a scoped branch directive.
