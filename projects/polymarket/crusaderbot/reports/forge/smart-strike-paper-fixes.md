# WARP-93 — Smart Strike Paper Fixes

Role: WARP•R00T
Branch: WARP/smart-strike-paper-fixes
Validation Tier: MAJOR (Issue 1 — exit/monitoring safety) + STANDARD (Issues 2–4)
Claim Level: NARROW INTEGRATION
Validation Target: the four paper-trade audit defects below — exit-loop scoping,
  preset timeframe persistence, the signal_following orphan audit, and the
  legacy-scan strategy_types bleed.
Not in Scope: ENABLE_LIVE_TRADING / the 5 validation flags / USE_REAL_CLOB /
  WARP-92 global toggle / kill_switch / SCORER_ACTIVE / ORCHESTRATOR_ACTIVE /
  Kelly a=0.25 / slippage gate / late_entry_v3 entry/exit logic / risk constants.
Suggested Next Step: WARP🔹CMD review (directive Stop Condition: Issue 1 is
  safety-critical → CMD review required before merge). Not self-merged.

---

## 1. What was built

Four scoped fixes from the Jun-8 live paper-trade audit (one commit per issue):

- **Issue 1 (MAJOR) — resolution_loss monitoring gap.** Root-caused and fixed at
  the correct layer. The directive assumed there was no sub-90s fast poll; in
  fact a dedicated 5s fast-exit loop already exists (`scheduler.check_candle_exits`
  → `registry.list_open_candle_positions_for_exit`, scoped to positions within
  `CLOSE_SWEEP_EXIT_NEAR_SEC=90`s of resolution and run every
  `CLOSE_SWEEP_EXIT_INTERVAL=5`s). The actual bug: `registry._CANDLE_PRESETS`
  (the fast-loop preset scope) was `("close_sweep","safe_close","flip_hunter")`
  — it OMITTED `candle_auto` (Smart Strike). So candle_auto positions only got
  the 30s `exit_watch`; a position entered <90s before a 5m candle's expiry gaps
  past its SL threshold to resolution before the next 30s tick and closes as
  `resolution_loss` (~-100%) instead of `sl_hit` (~-50%) — exactly the confirmed
  SOL case (entry 0.28, SL→0.14, opened 06:53:35, closed resolution_loss
  06:54:19). Fix: add `candle_auto` to `registry._CANDLE_PRESETS` so Smart Strike
  positions ride the existing 5s loop near resolution and the SL crossing is
  caught within ~5s. This satisfies every Issue-1 target-state bullet (ttl<90s →
  5s poll; ttl≥90s → 30s; recalculated per tick via the SQL
  `resolution_at <= NOW()+interval`; ZERO new DB calls on the hot path) at a far
  smaller, lower-risk surface than re-implementing poll cadence inside `run_once`.

- **Issue 2 (STANDARD) — selected_timeframe resets to 15m.** The only direct,
  auto-firing writer of `user_settings.selected_timeframe` is
  `router.activate_preset` (POST /autotrade/preset). The backend defaults
  crypto-short presets to `"5m"` — it never writes `"15m"` itself; the `"15m"`
  arrives in `body.selected_timeframe` from the web UI (a stale timeframe toggle
  re-POSTed on a later activation, ~86s after a manual 5m reset). candle_auto is
  the orchestrator-owned auto-router and LIVE v1 trades the 5m cells only (the
  Polymarket updown-15m series is discontinued → 15m == zero trades). Fix: at
  that single write path, pin `candle_auto` to `5m` regardless of the client
  value, with a `warning` log so the override stays observable. Single-rule
  crypto-short presets keep their toggle. (The operator-driven admin PATCH path
  is left intact — a deliberate operator 15m is allowed.)

- **Issue 3 (STANDARD) — signal_following orphan audit.** Full code+DB audit:
  `signal_following` is a real, registered `BaseStrategy` (StrategyRegistry
  bootstrap), wired to the Telegram `/signals` command, the live crash-recovery
  reconciler (`live_reconcile` directional prefix), DB enrollment migrations
  (012/031), and 70+ tests. The directive's "0 positions / enabled=false /
  orphaned" reflects it being DORMANT (no operator feed publishes → 0 candidates
  → 0 positions), NOT dead code. Deleting it would break imports, the registry
  lookup, the bot command surface, and the test suite. Action per the directive's
  "planned future strategy" branch (and the no-delete Stop Condition): added a
  RETAIN/do-not-delete audit comment to the class docstring; left code + DB row
  in place, disabled. No deletion, no routing change.

- **Issue 4 (STANDARD) — strategy_types stale on candle_auto users.** The new
  orchestrator (`signal_scan_job`) routes candle_auto purely by `active_preset`
  (deny-by-default) and ignores `strategy_types` entirely. But the LEGACY
  `scheduler.run_signal_scan` (still scheduled at `SIGNAL_SCAN_INTERVAL`) iterates
  `strategy_types` and dispatches to `copy_trade` — so a candle_auto user whose
  stale `strategy_types` still carries `'copy_trade'` would get copy_trade scans
  firing concurrently with their orchestrator late_entry_v3 flow (the
  "unintended fallback routing" the directive flagged). Fix (root cause): a guard
  in the legacy loop skips any user with a non-null/non-empty `active_preset` —
  any preset means orchestrator-owned and NO preset routes to copy_trade, so the
  truthy check is the precise ownership boundary and is future-proof to new
  presets (no hardcoded preset set to maintain — adopted from the Gemini review).
  Pre-preset copy_trade users (active_preset NULL) are unaffected. Plus migration
  092 collapses candle_auto users' `strategy_types` to `['late_entry_v3']` so the
  stored array matches code truth.

## 2. Current system architecture

DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING (unchanged).

- MONITORING: two exit loops — the 30s `exit_watch` (all open positions, Phase
  A+B) and the 5s `close_sweep_exit_fast` (candle presets within 90s of
  resolution, Phase A only). Issue 1 widens the fast loop's preset scope to
  include candle_auto; the loop, cadence, and SL/TP evaluation in
  `exit_watcher.evaluate` are otherwise untouched.
- STRATEGY routing: candle_auto → late_entry_v3 via `active_preset` in the new
  `signal_scan_job` (authoritative). The legacy `scheduler.run_signal_scan`
  copy_trade path now excludes any user with an active_preset (Issue 4 guard) —
  the two scan paths no longer overlap on orchestrator-owned users.
- API: `activate_preset` is the single auto-firing writer of `selected_timeframe`
  and now pins candle_auto to 5m (Issue 2).

## 3. Files created / modified (full repo-root paths)

Modified:
- projects/polymarket/crusaderbot/domain/positions/registry.py — `_CANDLE_PRESETS` += `candle_auto` (Issue 1)
- projects/polymarket/crusaderbot/webtrader/backend/router.py — candle_auto 5m pin in `activate_preset` (Issue 2)
- projects/polymarket/crusaderbot/domain/strategy/strategies/signal_following.py — RETAIN audit docstring (Issue 3)
- projects/polymarket/crusaderbot/scheduler.py — legacy-scan guard skips any active_preset user (Issue 4)
- projects/polymarket/crusaderbot/tests/test_close_sweep_fast_exit.py — updated preset-constant pin + candle_auto-in-scope test (Issue 1)

Created:
- projects/polymarket/crusaderbot/tests/test_candle_auto_timeframe_pin.py (Issue 2, 4 tests)
- projects/polymarket/crusaderbot/tests/test_legacy_scan_managed_preset_guard.py (Issue 4, 3 tests)
- projects/polymarket/crusaderbot/migrations/092_candle_auto_strategy_types.sql (Issue 4 data update; applied via CD)
- projects/polymarket/crusaderbot/migrations/rollback/092_candle_auto_strategy_types_rollback.sql
- projects/polymarket/crusaderbot/reports/forge/smart-strike-paper-fixes.md (this report)

## 4. What is working

- Targeted sweep over every touched module: 272 passed, ruff clean
  (test_close_sweep_fast_exit, test_candle_auto_timeframe_pin,
  test_legacy_scan_managed_preset_guard, test_candle_auto_router,
  test_strategy_registry, test_signal_following, test_admin_console,
  test_exit_watcher).
- Issue 1: `candle_auto ∈ registry._CANDLE_PRESETS`; fast loop scope test green.
- Issue 2: candle_auto 15m/None requests → persisted 5m; close_sweep keeps 15m.
- Issue 4: candle_auto + all 5 other managed presets skipped by the legacy scan;
  preset-less copy_trade user still scanned.

## 5. Known issues

- The exact runtime source that POSTs `15m` (Issue 2) is the web UI timeframe
  toggle; the backend pin neutralizes it regardless, but the frontend toggle
  could still DISPLAY 15m for candle_auto until refreshed. The persisted value is
  now always 5m. (Frontend toggle suppression for candle_auto is a follow-up if
  CMD wants the UI to match.)
- Migration 092 is a one-time data alignment; new candle_auto users created later
  still get default `strategy_types`, but the Issue 4 code guard makes that inert
  (managed-preset users are skipped regardless of the array).
- 4 pre-existing-unrelated `test_clob_pysdk.py` failures (missing optional
  `polymarket` module) persist — not touched by this lane.

## 6. What is next

- WARP🔹CMD review (Issue 1 safety-critical per directive Stop Condition). Not
  self-merged despite WARP•R00T merge authority — the directive explicitly gates
  merge on CMD review.
- On merge: migration 092 applies via CD before the scanner starts.
- Live verification of Issue 2 (walk3r69 stays 5m) can only be confirmed against
  prod after deploy; code logic is pinned by tests.
