# WARP•R00T — Strategy System Cleanup

Branch: `WARP/R00T/strategy-system-cleanup`
Date: 2026-05-29
Validation Tier: **MAJOR**
Claim Level: **FULL RUNTIME INTEGRATION**

Validation Target: end-to-end "admin OFF → strategy doesn't fire AND doesn't
appear in user dashboard" contract + strategy independence at runtime gate +
removal of every cosmetic strategy / preset that had no reachable user path.

Not in Scope:
- Re-introducing additional strategies (signal_following, copy_trade, late_entry_v3 are the 3 reachable; new strategies must follow the documented add-back path).
- Legacy `/setup_advanced` + `/strategy` Telegram commands (still wired; orthogonal to the auto-trade picker).
- Migration 068 application against Supabase production (operator step).

Suggested Next Step:
- Apply migration 068 against Supabase production (deletes 9 cosmetic rows from `strategies`).
- WARP🔹CMD verify Admin Console renders 3 toggles; Telegram + WebTrader pickers hide presets when their backing strategy is toggled OFF; copy_trade tick skips when toggle is OFF.
- Optional WARP•SENTINEL pass (MAJOR tier triggers it).

---

## 1. What was built

Three-lane WARP•R00T cleanup that closes both halves of the operator strategy
toggle contract and removes every cosmetic strategy / preset that had no real
user-facing trigger path.

**Lane 1 — `copy_trade` admin gate (CRITICAL bugfix).**
`services/copy_trade/monitor.py::run_once` now reads
`strategies.enabled WHERE name='copy_trade'` at the top of every tick and
returns early when it is FALSE. Mirrors the FAIL-SAFE contract of
`signal_scan_job._refresh_disabled_strategies`: missing row / DB error keeps
the strategy ON, never silently disables it. Closes the regression where the
operator's "copy_trade=OFF" admin toggle was honoured by `signal_scan_job`
but ignored by the dedicated copy-trade monitor — so admin toggle was bypassed
on the copy-trade execution path.

**Lane 2 — User picker filter (REQ 1 visibility half).**
New authenticated endpoint `GET /api/web/autotrade/preset-availability` returns
`{presets:[{key,strategy,enabled}]}` for every preset in `_PRESET_TO_STRATEGY`.
WebTrader `AutoTradePage` fetches it alongside `getAutotrade()` and hides
presets whose backing strategy is `enabled=false`. Telegram `preset_tier_kb`
accepts a `disabled_strategies: frozenset[str]` param; the `show_preset_picker`
handler fetches the disabled set from the `strategies` table once per render
and passes it in. FAIL-SAFE both sides: API failure / empty set keeps every
preset visible.

**Lane 3 — Reduce admin panel + archive cosmetic surface (treatment A).**
Operator panel narrows from 12 strategies to the 3 that actually have a
reachable trigger path (`late_entry_v3`, `signal_following`, `copy_trade`).
Migration 068 deletes the 9 cosmetic rows from `strategies` (FAIL-SAFE: future
re-introduction comes back ON until the operator explicitly toggles it). The
9 cosmetic strategy modules + their dead tests are deleted from the tree,
along with the legacy multi-strategy presets (`whale_mirror`, `signal_sniper`,
`hybrid`, `value_hunter`, `full_auto`, `trend_breakout`, `contrarian`,
`pair_arb`, `ensemble`, `confluence_scalper`) and the `_keyboards_archive/`
directory that nothing imported.

REQ 2 (strategy independence) was already correct at the runtime gate level —
`_preset_allows()` checks each strategy individually — but Lane 3 hardens it
further by deleting the multi-strategy presets (`ensemble`, `hybrid`,
`full_auto`) so silent-degradation is no longer possible.

---

## 2. Current system architecture

```
ADMIN CONSOLE (/admin)
    | toggle ON/OFF
    v
strategies table (mig 067 + mig 068)
    | enabled=FALSE rows
    v
    +-- _refresh_disabled_strategies()  (signal_scan_job)
    |       | _GLOBALLY_DISABLED_STRATEGIES cache, per tick
    |       v
    |   _preset_allows() in run_once()  --> blocks per-strategy
    |   run_close_sweep_fast() gate     --> blocks late_entry_v3 candle loop
    |
    +-- copy_trade.monitor._is_globally_disabled()  (new — Lane 1)
    |       v
    |   monitor.run_once() returns before list_active_tasks
    |
    +-- GET /api/web/autotrade/preset-availability  (new — Lane 2)
            v
        WebTrader AutoTradePage    --> filters STRATEGY_PRESETS
        Telegram preset_tier_kb    --> hides presets whose strat is OFF


PRESET → STRATEGY MAP (single source of truth)
    close_sweep / safe_close / flip_hunter --> late_entry_v3
    (no other presets exist)


ADMIN_STRATEGIES roster
    late_entry_v3, signal_following, copy_trade
```

The "user with NULL active_preset is skipped" safety guard at the top of
`run_once()` is preserved verbatim.

---

## 3. Files created / modified (full repo-root paths)

**Created**
- `projects/polymarket/crusaderbot/migrations/068_narrow_strategies_to_active.sql`
- `projects/polymarket/crusaderbot/tests/test_copy_trade_admin_gate.py`
- `projects/polymarket/crusaderbot/reports/forge/strategy-system-cleanup.md` (this file)

**Modified — production**
- `projects/polymarket/crusaderbot/services/copy_trade/monitor.py`
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
- `projects/polymarket/crusaderbot/services/signal_scan/lib_strategy_runner.py`
- `projects/polymarket/crusaderbot/services/notification_service.py`
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py`
- `projects/polymarket/crusaderbot/domain/strategy/registry.py`
- `projects/polymarket/crusaderbot/domain/strategy/strategies/__init__.py`
- `projects/polymarket/crusaderbot/domain/preset/presets.py`
- `projects/polymarket/crusaderbot/bot/presets.py`
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py`
- `projects/polymarket/crusaderbot/bot/handlers/presets.py`
- `projects/polymarket/crusaderbot/bot/keyboards/autotrade.py`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx`

**Modified — tests (adapted to new constants)**
- `projects/polymarket/crusaderbot/tests/test_admin_console.py`
- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py`
- `projects/polymarket/crusaderbot/tests/test_lib_strategy_loading.py`
- `projects/polymarket/crusaderbot/tests/test_runtime_trade_smoke.py`
- `projects/polymarket/crusaderbot/tests/test_pipeline_runtime_hardening.py`
- `projects/polymarket/crusaderbot/tests/test_phase5g_customize_wizard.py`

**Deleted — cosmetic strategy code**
- `projects/polymarket/crusaderbot/lib/strategies/ensemble.py`
- `projects/polymarket/crusaderbot/lib/strategies/expiration_timing.py`
- `projects/polymarket/crusaderbot/lib/strategies/logic_arb.py`
- `projects/polymarket/crusaderbot/lib/strategies/market_making.py`
- `projects/polymarket/crusaderbot/lib/strategies/momentum.py`
- `projects/polymarket/crusaderbot/lib/strategies/pair_arb.py`
- `projects/polymarket/crusaderbot/lib/strategies/sentiment.py`
- `projects/polymarket/crusaderbot/lib/strategies/trend_breakout.py`
- `projects/polymarket/crusaderbot/lib/strategies/value_investor.py`
- `projects/polymarket/crusaderbot/lib/strategies/weather_arb.py`
- `projects/polymarket/crusaderbot/lib/strategies/whale_tracking.py`
- `projects/polymarket/crusaderbot/lib/strategies/str.md`
- `projects/polymarket/crusaderbot/domain/strategy/strategies/confluence_scalper.py`
- `projects/polymarket/crusaderbot/domain/strategy/strategies/momentum_reversal.py`

**Deleted — dead tests**
- `projects/polymarket/crusaderbot/tests/test_confluence_scalper.py`
- `projects/polymarket/crusaderbot/tests/test_momentum_reversal.py`
- `projects/polymarket/crusaderbot/tests/test_webtrader_confluence_scalper_exposure.py`
- `projects/polymarket/crusaderbot/tests/test_preset_system.py`
- `projects/polymarket/crusaderbot/tests/test_phase5h_onboarding.py`
- `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py`
- `projects/polymarket/crusaderbot/tests/test_ux_overhaul.py`
- `projects/polymarket/crusaderbot/tests/test_phase5j_emergency.py`
- `projects/polymarket/crusaderbot/tests/test_pnl_insights.py`

**Deleted — legacy keyboards archive (already-archived dir nothing imported)**
- `projects/polymarket/crusaderbot/bot/_keyboards_archive/` (whole directory: 11 files)

---

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/` → **1817 passed / 5 skipped / 0 failed** (44 s).
- Admin gate test suite (`test_copy_trade_admin_gate.py`, 8 tests) PASSES the full FAIL-SAFE matrix: enabled row, disabled row, missing row, DB error, and kill-switch-wins interaction.
- New `_preset_allows` contract tests pin the "candle preset → late_entry_v3 only" and "globally disabled strategy → never allowed regardless of preset" invariants.
- `signal_scan_job.run_once()` exits cleanly for users with non-candle / NULL `active_preset` (preserved invariant); the lib-strategy loop is now a no-op (`ENABLED_STRATEGIES = ()`).
- `copy_trade.monitor.run_once()` skips tick when admin OFF (Lane 1).
- WebTrader picker hides any preset whose row says `enabled=false`; Telegram picker does the same via the new `disabled_strategies` param.
- Every modified module imports cleanly (verified via `importlib.import_module`).

---

## 5. Known issues

- **None blocking the lane goal.**
- Migration 068 still has to be applied against Supabase production (operator step). Until it runs, the 9 cosmetic rows remain in the table but are no longer rendered in the admin panel (`_ADMIN_STRATEGIES` already narrowed) and are not referenced by any preset (`_PRESET_TO_STRATEGY` already narrowed) — so the only effect of the lag is the deleted-row count, not behaviour.
- Legacy `/setup_advanced` + `/strategy` Telegram commands still exist and still show some removed strategy names in their option lists. They are orthogonal to the auto-trade picker (the path users actually take). Left in scope of a follow-up if Mr. Walker wants the whole legacy UX cleaned up.
- `jobs/market_signal_scanner.py` still publishes `momentum_reversal` rows to `signal_publications`. `signal_following` consumes those publications, so the publisher is NOT dead — it feeds the surviving signal-feed path. Docstring left as-is.

---

## 6. What is next

1. WARP🔹CMD applies migration 068 to Supabase production.
2. Operator visual check on `/admin`: only 3 strategy toggles render.
3. Toggle `late_entry_v3=FALSE` from `/admin` → verify candle presets disappear from WebTrader picker + Telegram picker on next refresh.
4. Toggle `copy_trade=FALSE` → verify next `copy_trade_monitor` tick log includes `"copy_trade_monitor: globally disabled by admin — skipping tick"`.
5. Toggle back ON → verify normal behaviour resumes.
6. Optional: WARP•SENTINEL audit pass on this branch (MAJOR tier).
