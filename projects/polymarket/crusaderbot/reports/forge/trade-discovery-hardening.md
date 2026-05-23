# WARP•FORGE Report — Trade-Discovery Hardening

Branch: WARP/trade-discovery-hardening
Role: WARP•FORGE
Date: 2026-05-24 02:10 Asia/Jakarta
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: market-discovery resolution-horizon enforcement (#2), demo signal-generator universe breadth + horizon cap (#3), and concurrency-slot release for far-dated positions (#4) — across the signal-scan, signal-feed, scanner, risk-eligibility, positions-registry, and exit-watcher modules.
Not in Scope: the edge-scoring model bug (#1, `edge = abs(yes_price - 0.5)`) — DEFERRED to a separate strategy lane per WARP🔹CMD; force-closing the 20 far-dated futures held by aggressive-profile users (owner decision); any live-trading activation (guards remain OFF).
Suggested Next Step: WARP•SENTINEL validation (MAJOR), then Fly.io redeploy + live confirmation that new entries are short-dated/diverse and the balanced user's stuck slots auto-close.

---

## 1. What was built

A three-layer fix for the closed-beta report (tester Vitalix: *"bot found only 5 trades in a week, always the same 5, 0 profit, looks like it can't find other positions"*). The symptom was confirmed against the live database: **all 25 open positions across the 5 auto-trading users are far-dated 2026/2028 championship-winner futures** (NHL Stanley Cup / NBA Finals / FIFA World Cup, resolving Jun–Jul 2026), each at ~$0 PnL, occupying every one of the 5 concurrency slots per user (`MAX_CONCURRENT_TRADES = 5`). Because these markets do not resolve for months and barely move, they never hit TP/SL and never free a slot — so the bot can never open anything new.

Root causes addressed:

- **#2 — Resolution horizon was never enforced on the active path.**
  - `signal_scan_job._build_market_filters()` hardcoded `max_time_to_resolution_days = 365`, which is exactly `copy_trade.RESOLUTION_DISTANCE_DISABLED_DAYS` — the sentinel that *disables* the resolution-distance check entirely — plus `min_liquidity = 0.0`.
  - `signal_feed/signal_evaluator.py` explicitly documented `max_time_to_resolution_days -> NOT enforced` ("requires HTTP"), but `markets.resolution_at` is a local synced column, so the no-HTTP constraint was never actually a blocker.
  - Fix: filters are now derived from the user's risk profile via `PROFILES` (conservative 7d/$20k, balanced 30d/$15k, aggressive 90d/$10k), and the evaluator enforces the horizon with a `LEFT JOIN markets` clause (pure DB read; NULL resolution kept; the 365 sentinel still disables).

- **#3 — The demo edge generator surfaced a narrow, far-dated universe.**
  - `jobs/market_signal_scanner.py` fetched only `get_markets(limit=200)` with no sort and no horizon bound, so it churned the same ~188 markets — dominated by long-dated championship futures.
  - Fix: it now fetches `SCANNER_MARKET_FETCH_LIMIT` (500) markets ordered by 24h volume, with a `SCANNER_MAX_RESOLUTION_DAYS` (30) horizon cap applied both server-side (`end_date_max`) and client-side (defensive skip), so far-dated futures are never published to any user. `integrations/polymarket.get_markets` gained optional `order` / `ascending` / `end_date_max` params (defaults preserve all existing callers).

- **#4 — Slots stayed locked by far-dated positions.**
  - There was no time/horizon-based exit; the watcher chain was force-close → TP → SL → strategy → hold.
  - Fix: added `ExitReason.HORIZON_EXCEEDED` and a last-priority `_horizon_exceeded` check in `exit_watcher.evaluate()` that closes a position when its market resolves beyond the **owning user's** profile horizon. `OpenPositionForExit` now carries `resolution_at` + `risk_profile` (`list_open_for_exit` `LEFT JOIN user_settings`). This frees the balanced user's 5 stuck slots on deploy and is self-healing thereafter.

---

## 2. Current system architecture

```
DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING
```

Discovery → entry → exit flow after this lane:

```
market_signal_scanner (demo edge gen)
  └─ get_markets(limit=500, order=volume24hr, end_date_max=now+30d)   [#3 universe + horizon cap]
  └─ client-side skip if resolution_at > now+SCANNER_MAX_RESOLUTION_DAYS
  └─ publishes near-dated, liquid markets to signal_publications

signal_scan_job.run_once (per enrolled user)
  └─ _build_market_filters(profile) → MarketFilters(max_days, min_liq from PROFILES)  [#2]
  └─ signal_evaluator.evaluate_publications_for_user
        └─ _load_active_publications(..., max_resolution_days)
              └─ LEFT JOIN markets; drop pubs resolving beyond horizon  [#2 enforce]
  └─ risk gate (unchanged) → TradeEngine → positions

exit_watcher.run_once (every EXIT_WATCH_INTERVAL)
  └─ evaluate(): force_close → TP → SL → strategy → HORIZON_EXCEEDED → hold  [#4]
        └─ _horizon_exceeded(position): resolution_at vs PROFILES[profile].max_days
```

No change to the locked pipeline order, the risk gate, the kill switch, or the activation guards. All work is paper-mode reproducible.

---

## 3. Files created / modified (full repo-root paths)

Modified (production):
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — import `PROFILES`; `_build_market_filters(profile)` derives `max_time_to_resolution_days` + `min_liquidity` from the profile (both call sites pass `user_ctx.risk_profile`).
- `projects/polymarket/crusaderbot/services/signal_feed/signal_evaluator.py` — enforce resolution horizon in `_load_active_publications` (LEFT JOIN `markets`, conditional clause, sentinel disable); `RESOLUTION_DISTANCE_DISABLED_DAYS` constant; docstring corrected; caller passes `market_filters.max_time_to_resolution_days`.
- `projects/polymarket/crusaderbot/integrations/polymarket.py` — `get_markets` gains optional `order` / `ascending` / `end_date_max` (cache-key + params extended; defaults unchanged).
- `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py` — demo path fetches `SCANNER_MARKET_FETCH_LIMIT` markets ordered by 24h volume with `end_date_max` + client-side horizon guard.
- `projects/polymarket/crusaderbot/config.py` — `SCANNER_MARKET_FETCH_LIMIT=500`, `SCANNER_MAX_RESOLUTION_DAYS=30`.
- `projects/polymarket/crusaderbot/domain/positions/registry.py` — `ExitReason.HORIZON_EXCEEDED` (+ WATCHER_EXIT_REASONS); `resolution_at` + `risk_profile` on `OpenPositionForExit`; `list_open_for_exit` LEFT JOINs `user_settings` and selects `m.resolution_at`.
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` — `_horizon_exceeded` helper + last-priority HORIZON_EXCEEDED branch in `evaluate()`; imports `timedelta`, `PROFILES`.

Modified (tests):
- `projects/polymarket/crusaderbot/tests/test_market_signal_scanner.py` — `_FAKE_CFG` gains the 2 new settings fields.
- `projects/polymarket/crusaderbot/tests/test_exit_watcher.py` — `_make_position` accepts `resolution_at` / `risk_profile`; 5 new horizon-exit cases.

Created:
- `projects/polymarket/crusaderbot/reports/forge/trade-discovery-hardening.md` (this report).

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` (Last Updated, Status, [IN PROGRESS], [NEXT PRIORITY], [KNOWN ISSUES]).
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` (append).

---

## 4. What is working

- `python -m py_compile` clean on all 7 modified production files.
- 185 affected tests pass:
  - `test_exit_watcher.py` — 36 (incl. 5 new: horizon close for balanced, hold within horizon, aggressive keeps 60d, TP wins over horizon, NULL resolution never closed).
  - `test_market_signal_scanner.py` — 11 (fixture updated for the 2 new config fields).
  - `test_signal_following.py`, `test_signal_scan_job.py`, `test_confluence_scalper.py`, `test_momentum_reversal.py`, `test_copy_trade.py`, `test_phase5e_copy_trade.py` — green (no regression from the `MarketFilters`/registry/get_markets signature changes).
- DB check: `positions.exit_reason` has no CHECK constraint, so the new `horizon_exceeded` value persists cleanly.
- Backward compatibility: `get_markets` defaults unchanged (webtrader router caller unaffected); the resolved-market Phase B path is unaffected (new dataclass fields default to `None`/`balanced`).

---

## 5. Known issues

- **Edge-model bug #1 (DEFERRED).** The demo generator scores edge as `edge = abs(yes_price - 0.5)` ("fair value baseline 0.5"), which treats longshots/extremes as high-edge and systematically buys championship-winner longshots → "0 profit, only some lose." This lane fixed discovery/horizon/slot-lock but NOT the scoring model (WARP🔹CMD chose "structural first"). A dedicated strategy lane is required.
- **Aggressive-user stuck futures NOT auto-closed.** The 20 far-dated futures held by the 4 aggressive-profile users are within their 90d mandate, so the per-profile HORIZON_EXCEEDED exit correctly does not close them. They will clear on natural resolution (~Jun–Jul 2026) or when #1 lands. Prod positions were not force-closed without owner sign-off; WARP🔹CMD may request a one-time paper reset as a separate step.
- **Live-runtime proof pending.** Validation here is unit-test + live-DB analysis. End-to-end confirmation (new entries short-dated/diverse; balanced slots freed) requires a Fly.io redeploy.
- **Gamma param names.** `order` / `ascending` / `end_date_max` follow Gamma's documented snake_case query params; if Gamma ignores any, the client-side horizon guard still enforces the cap (defense in depth) and ordering merely affects which 500 are sampled.

---

## 6. What is next

1. WARP•SENTINEL validation (MAJOR) — verify per-profile horizon enforcement (feed + filters), scanner horizon cap, and the exit-watcher priority ordering; confirm guards untouched.
2. WARP🔹CMD merge decision.
3. Fly.io redeploy; confirm via scan telemetry that new entries are short-dated and diverse, and that the balanced user's stuck slots auto-close on the next exit-watch tick.
4. Open the deferred lane for edge-model bug #1 (replace `|p-0.5|` with a real edge definition); decide whether to one-time-reset the 20 aggressive-user futures.
