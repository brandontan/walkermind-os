# WARP•FORGE Report — PLAYBOOK Sports Engine (Phase 1)

- **Branch:** `WARP/ROOT/playbook-sports-engine`
- **Linear:** WARP-53
- **Validation Tier:** MAJOR
- **Claim Level:** FOUNDATION
- **Validation Target:** The PLAYBOOK strategy router foundation — `domain/playbook/`
  package (market quality filter, native signal layer, precedence-claim router, Closing
  Edge module + declared stubs), the `PlaybookStrategy` BaseStrategy adapter, and the
  `playbook` preset wired through registry + risk `STRATEGY_AVAILABILITY` + backend +
  Telegram + WebTrader. Paper-mode only.
- **Not in Scope:** live signal-scan-loop runtime dispatch (Phase 2); external feed
  adapters (odds/injury/news); the backtest and Monte-Carlo frameworks; CLOB WebSocket
  streaming; the Sharp Money / Public Fade / Injury Alpha module trade logic (declared
  stubs only).
- **Suggested Next Step:** WARP•SENTINEL MAJOR validation, then Phase-2 lane
  `WARP/ROOT/playbook-live-dispatch` wiring `playbook` into `signal_scan_job` via the
  `weather_monitor` → `weather` precedent.

---

## 1. What was built

PLAYBOOK — the sports equivalent of SMART STRIKE: an autonomous strategy *router* that
evaluates each Polymarket sports market and routes capital to the highest-EV sports
module. Phase-1 delivers the full design blueprint plus a coded FOUNDATION: the router
spine + Market Quality Filter + native signal layer + the **Closing Edge** module
(Polymarket-native MVP), surfaced as a single `playbook` auto preset. The other three
matrix modules (Sharp Money, Public Fade, Injury Alpha) are declared and stubbed.

PLAYBOOK reuses the existing production machinery unchanged — the 13-step risk gate
(fractional Kelly ≤ 0.25, max position ≤ 10%, daily-loss, drawdown, exposure, kill
switch), the execution router (paper/live + 5 activation guards), the exit watcher, and
Telegram alerts. It introduces no new risk or execution authority.

Design blueprint: `docs/blueprint/playbook.md` (per-league alpha analysis, signal
formulas, routing matrix, correlation engine, risk profiles, UI, MVP, V2/V3 roadmaps,
highest-EV plan, backtest + Monte-Carlo specs).

## 2. Current system architecture

```
Sports Market
   → Market Quality Filter   (domain/playbook/market_quality.py)   NEW
   → Signal Layer            (domain/playbook/signals.py, feeds.py) NEW
   → Playbook Router         (domain/playbook/router.py)            NEW  precedence-claim
   → Correlation Engine      (domain/playbook/correlation.py)       NEW  cluster_key
   → Risk Manager            (domain/risk/gate.py)                  REUSED unchanged
   → Execution Engine        (domain/execution/router.py)          REUSED unchanged
   → Monitoring / Telegram   (monitoring/alerts.py)                REUSED
```

One `PlaybookStrategy(BaseStrategy)` (`name="playbook"`) owns the router + modules,
exactly as `LateEntryV3Strategy` owns the Close/Safe/Flip rules behind `candle_auto`.
The router walks modules in precedence order (injury_alpha → sharp_money → closing_edge
→ public_fade); the first to claim a market wins (dedup-by-design). The strategy emits a
standard `SignalCandidate` with the selected module + confidence in `metadata`.

Runtime-dispatch posture: `_PRESET_ALLOWED` in `signal_scan_job.py` is deny-by-default,
so `playbook` is registered + selectable but fires nothing live until Phase-2 — the
FOUNDATION posture. `PlaybookStrategy.scan()` also returns `[]` in Phase-1 (no sports
data source wired); the decision core is exercised via `evaluate_snapshot`.

## 3. Files created / modified (full repo-root paths)

Created:
- `docs/blueprint/playbook.md`
- `projects/polymarket/crusaderbot/domain/playbook/__init__.py`
- `projects/polymarket/crusaderbot/domain/playbook/market_quality.py`
- `projects/polymarket/crusaderbot/domain/playbook/signals.py`
- `projects/polymarket/crusaderbot/domain/playbook/feeds.py`
- `projects/polymarket/crusaderbot/domain/playbook/correlation.py`
- `projects/polymarket/crusaderbot/domain/playbook/router.py`
- `projects/polymarket/crusaderbot/domain/playbook/modules.py`
- `projects/polymarket/crusaderbot/domain/strategy/strategies/playbook.py`
- `projects/polymarket/crusaderbot/tests/test_playbook_engine.py`
- `projects/polymarket/crusaderbot/reports/forge/playbook-sports-engine.md`

Modified:
- `projects/polymarket/crusaderbot/domain/strategy/strategies/__init__.py` (export)
- `projects/polymarket/crusaderbot/domain/strategy/registry.py` (bootstrap tuple)
- `projects/polymarket/crusaderbot/domain/preset/presets.py` (playbook preset + orders)
- `projects/polymarket/crusaderbot/domain/risk/constants.py` (STRATEGY_AVAILABILITY)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
  (`_PRESET_TO_STRATEGY` / `_PRESET_PARAMS` / `_PRESET_LOCKED_CATEGORY` / `_ADMIN_STRATEGIES`)
- `projects/polymarket/crusaderbot/bot/presets.py` (PRESET_CONFIG + PRESET_ORDER)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`
  (Playbook card + TOP_LEVEL_PRESET_KEYS + PRESET_LOCKED_CATEGORY)
- `projects/polymarket/crusaderbot/tests/test_admin_console.py` (roster pins)
- `projects/polymarket/crusaderbot/tests/test_resume_safety_check.py` (covered via availability)

## 4. What is working

- Market Quality Filter accepts healthy books, rejects on liquidity / spread / depth /
  resolution / integrity (verified).
- Native signal formulas (line movement, liquidity, TTL, sentiment, sharp-money proxy)
  produce clamped [0,1] confidences; feed-dependent signals fall back to neutral.
- `PlaybookRouter` routes a stale-book sports snapshot to `closing_edge` (YES/NO by
  higher edge) and returns no-claim when TTL is outside the close window or edge < min;
  stub modules never claim in Phase-1.
- `PlaybookStrategy.evaluate_snapshot` emits a correct `SignalCandidate`
  (`selected_module`, `cluster_key`, `engine=playbook`, per-module TP/SL); `scan()`
  returns `[]` (FOUNDATION); `evaluate_exit` force-exits inside the module window and
  holds otherwise.
- `playbook` registers in `StrategyRegistry`, validates as a preset, is routable at risk
  gate step 4, and appears in WebTrader + Telegram pickers (locks category → Sports).
- **Full test suite: 2371 passed, 0 failed.** New `test_playbook_engine.py` = 24 cases.
  `ruff` clean on all new files.

## 5. Known issues

- None functional. By design (FOUNDATION): `scan()` returns `[]` and the scanner does
  not dispatch `playbook` until Phase-2 — so activating the preset produces zero live
  trades today. This is the intended paper-only foundation posture, not a defect.
- Sharp Money carries a native formula but its on-chain accumulation source is a proxy
  (zeroed) until V2 wires the copy-trade chain monitor.

## 6. What is next

1. WARP•SENTINEL MAJOR validation (Phase-0 + risk/exposure non-regression).
2. Phase-2a: `WARP/ROOT/playbook-live-dispatch` — wire `playbook` into `_PRESET_ALLOWED`
   + `_DOMAIN_STRATEGY_NAMES` + a scheduler scan job + the sports-market snapshot fetch
   in `_fetch_sports_snapshots` (weather precedent). Validate closing-line capture in
   paper.
3. Phase-2b: promote Sharp Money to live on-chain source.
4. Phase-2c: backtest framework (shared blocker; unblocks candle + sports +EV proof).
5. Phase-2d/e: Injury Alpha + Public Fade once their external feed adapters land.
