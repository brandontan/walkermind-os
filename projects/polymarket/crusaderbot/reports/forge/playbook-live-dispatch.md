# WARP•FORGE Report — PLAYBOOK Live Dispatch (Phase 2a)

- **Branch:** `WARP/ROOT/playbook-live-dispatch`
- **Linear:** WARP-53
- **Validation Tier:** MAJOR
- **Claim Level:** FULL RUNTIME INTEGRATION (paper)
- **Validation Target:** Wiring the `playbook` strategy into the live signal-scan
  loop — sports-market snapshot fetch (`PlaybookStrategy._fetch_sports_snapshots`),
  Phase-B4 dispatch in `signal_scan_job.run_once`, operator enable-flag, and re-enabling
  the preset (visibility + activation) now that dispatch is live. PAPER-only.
- **Not in Scope:** Sharp Money live on-chain source (2b), backtest framework (2c),
  external feed adapters / Injury Alpha / Public Fade (2d/2e), CLOB WebSocket + Monte
  Carlo (Phase 3). LIVE trading stays behind the existing 5 activation guards.
- **Suggested Next Step:** WARP•SENTINEL MAJOR validation, then Phase-2b (Sharp Money).

---

## 1. What was built

PLAYBOOK now actually trades sports markets in paper. The previously FOUNDATION-only
router is wired into the live scan cadence:

- **Sports snapshot fetch** — `PlaybookStrategy._fetch_sports_snapshots` fetches Gamma
  events (`get_events_with_markets`, cached 300s), pre-filters to sports categories
  within a 2h pre-event window (bounds orderbook reads + matches the Closing-Edge entry
  window), then reads each leg's CLOB book (`get_book`, cached 30s) and assembles a
  `MarketSnapshot`. Every external call is fail-soft.
- **Phase-B4 dispatch** — `signal_scan_job.run_once` now scans the `playbook` strategy
  for users on the `playbook` preset, gated by the `PLAYBOOK_STRATEGY_ENABLED` operator
  flag (runtime-overridable), emitting candidates through the same `_process_candidate`
  → risk-gate → execution path as every other strategy (mirrors weather Phase-B2).
- **Preset re-enabled** — since dispatch is live, `playbook` is restored to the
  WebTrader top-level picker, the Telegram picker, and `VISIBLE_PRESET_ORDER`;
  `HIDDEN_PRESETS` is now empty (the activation-gate machinery from PR #1570 stays for
  future deferred presets).
- **Fair-value fix** — Closing-Edge `fair_price` is taken from the Gamma consensus price
  (independent of the live CLOB ask), so a CLOB resting order below consensus surfaces as
  a positive edge. (A book-mid fair would make `fair − ask` structurally ≤ 0 and the
  module would never fire.)

## 2. Current system architecture

```
run_once(user) →
  Phase B (late_entry_v3) … Phase B2 (weather) …
  Phase B4 (playbook):  gate on preset==playbook AND PLAYBOOK_STRATEGY_ENABLED
     → PlaybookStrategy.scan(market_filters, user_ctx)
         → _fetch_sports_snapshots: Gamma sports markets (≤2h to event)
                                    + CLOB books → MarketSnapshot[]
         → evaluate_snapshot: quality → signals → PlaybookRouter (Closing Edge)
         → SignalCandidate[]
     → _process_candidate → 13-step risk gate → execution router (paper)
```

The risk gate, execution router, exit watcher, and monitoring are unchanged. Dispatch is
deny-by-default: a non-`playbook` preset never triggers it, and the operator flag is the
runtime kill-switch (default OFF in config, `true` in `fly.toml` for paper).

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/strategies/playbook.py` (real fetch + helpers + fair-value)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (Phase-B4 dispatch + roster)
- `projects/polymarket/crusaderbot/config.py` (`PLAYBOOK_STRATEGY_ENABLED`)
- `projects/polymarket/crusaderbot/domain/ops/runtime_config.py` (runtime overlay spec)
- `projects/polymarket/crusaderbot/fly.toml` (`PLAYBOOK_STRATEGY_ENABLED='true'`)
- `projects/polymarket/crusaderbot/domain/preset/presets.py` (empty `HIDDEN_PRESETS`, re-add to visible)
- `projects/polymarket/crusaderbot/bot/presets.py` (re-add to picker order)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx` (re-add top-level card)
- `projects/polymarket/crusaderbot/tests/test_playbook_engine.py` (dispatch + snapshot + helper tests)

Created:
- `projects/polymarket/crusaderbot/reports/forge/playbook-live-dispatch.md`

## 4. What is working

- Mocked end-to-end: a stale-book NFL market (Gamma fair 0.60, CLOB YES ask 0.55, 10 min
  to kickoff) routes to Closing Edge and emits a YES `SignalCandidate` through `scan()`.
- Out-of-window markets are skipped before any book fetch; a Gamma fetch error yields
  an empty scan (fail-soft).
- Dispatch wiring asserted: `playbook` in `_PRESET_ALLOWED` + `_DOMAIN_STRATEGY_NAMES`;
  `_preset_allows` deny-by-default for other presets.
- Preset re-enabled + activatable; backend/bot/risk rosters in sync.
- **Full suite: 2410 passed, 0 failed.** `ruff` clean.

## 5. Known issues

- Closing Edge only acts within 30 min of an event, so candidates are sparse outside
  game windows — expected. Sharp Money / Public Fade / Injury Alpha remain stubs.
- `fair_price` relies on the Gamma consensus price; if Gamma lags badly the edge
  estimate inherits that lag. Acceptable for paper; a model/consensus feed is V2.
- Live external feeds (2d/2e) need owner-provisioned API keys + network allowlist.

## 6. What is next

1. WARP•SENTINEL MAJOR validation (Phase-B4 dispatch + risk-path non-regression).
2. Owner: keep `PLAYBOOK_STRATEGY_ENABLED` on in paper, observe closing-line capture.
3. Phase-2b — Sharp Money live on-chain source (copy-trade chain monitor).
4. Phase-2c — backtest framework.
