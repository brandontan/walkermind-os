# Candle Auto Router — "Smart Strike" preset

**Role:** WARP•R00T (build)
**Branch:** `WARP/ROOT/candle-auto-router`
**Validation Tier:** MAJOR (trading-core scan + exit path)
**Claim Level:** NARROW INTEGRATION (PAPER path wired end-to-end; LIVE path has a documented gap — see Known Issues)
**Validation Target:** the `candle_auto` lifecycle-router preset (entry routing + per-rule exit threading) and its activation surfaces
**Not in Scope:** removing/altering the 3 single-rule presets; flipping activation guards; LIVE execution `strategy_metadata` persistence; backtesting/EV validation of the combined router

---

## 1. What was built

A new **additive** candle preset — internal key `candle_auto`, user-facing name
**🔥 Smart Strike** — that combines the three single-rule candle presets
(`close_sweep`, `safe_close`, `flip_hunter`) into ONE preset that routes to the
same `late_entry_v3` engine. Per market, it picks whichever rule fits the candle's
lifecycle stage and keeps that rule's exit:

```
seconds_to_close:   180s ───────── 60s ──── 35s ──── 0s
rule:               │  flip_hunter  │ safe  │  close_sweep │
side:               │   underdog    │ favorite (both)       │
force-exit:         │  hold to $1   │ rem30 │  rem 8s        │
```

The three single-rule presets are **untouched** — advanced users can still pick
them individually. `candle_auto` is the new RECOMMENDED preset (set-and-forget).

Design rationale + the per-rule-exit constraint come from the WARP-51 alpha audit
(`reports/forge/strategic-alpha-research.md`): the rules' exits/TP-SL are different
theses and must NOT be merged into one — so the router threads each matched rule's
`force_exit_at_rem_sec` + `tp/sl` per candidate.

## 2. Current system architecture

- **Entry router** (`services/signal_scan/signal_scan_job.py`): new
  `_scan_late_entry_for_preset()` is the single entry point used by BOTH scan
  loops (`run_once` 180s + `run_close_sweep_fast` ~15s). For `candle_auto` it scans
  each single rule (`_scan_one_late_entry` per rule), stamps `candle_rule` +
  `applied_tp_pct`/`applied_sl_pct` (sourced from the canonical domain `PRESETS`)
  into each candidate's `metadata`, and dedups by `market_id` with precedence
  `close_sweep > safe_close > flip_hunter`. The only real window overlap is
  ~30–35s (close_sweep vs safe_close, same favorite side) where close_sweep wins;
  flip_hunter is the opposite (underdog) side and time-disjoint, so it never
  conflicts on side.
- **Per-rule TP/SL** (`signal_scan_job._build_trade_signal`): candidate-supplied
  `applied_tp_pct`/`applied_sl_pct` override the user-level tp/sl, so each
  position carries its own rule's TP/SL and the existing exit chain handles it
  unchanged. Non-router strategies leave these keys unset → no behaviour change.
- **Per-rule force-exit** (`domain/execution/exit_watcher.py`): for `candle_auto`,
  `force_exit_at_rem_sec_for(active_preset, tf)` returns None (no map entry), so
  the watcher falls back to the value persisted in `positions.strategy_metadata`
  (stamped at scan time, carried via the existing weather-style metadata thread).
- **Constants** (`signal_scan_job.py`): `_CANDLE_PRESETS` stays the 3 single rules
  (it drives `_resolve_preset_params` single-rule dispatch); a new
  `_ALL_CANDLE_PRESETS = _CANDLE_PRESETS | {candle_auto}` gates window-fetch +
  fast-loop membership. `_PRESET_ALLOWED["candle_auto"] = {late_entry_v3}`.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/domain/preset/presets.py` — `candle_auto` Preset (🔥 Smart Strike) + orders + CANDLE_PRESET_KEYS + RECOMMENDED_PRESET
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — `_PRESET_ALLOWED`, `_ALL_CANDLE_PRESETS`, `_CANDLE_AUTO_RULE_ORDER`, `_candle_auto_rule_tpsl`, `_scan_one_late_entry`, `_scan_late_entry_for_preset`; both scan loops refactored to the helper; `_build_trade_signal` per-rule tp/sl override
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` — `candle_auto` force-exit fallback from `strategy_metadata`
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` — `candle_auto` in `_PRESET_TO_STRATEGY`, `_PRESET_PARAMS`, `_CRYPTO_SHORT_PRESETS`, `_PRESET_LOCKED_CATEGORY`
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx` — Smart Strike card + `CRYPTO_SHORT_PRESETS` + `PRESET_LOCKED_CATEGORY`
- `projects/polymarket/crusaderbot/bot/presets.py` — `candle_auto` PRESET_CONFIG + PRESET_ORDER
- `projects/polymarket/crusaderbot/bot/handlers/presets.py` — `_MVP_LABELS` + `_MVP_DESCRIPTIONS`
- `projects/polymarket/crusaderbot/tests/test_close_sweep_spread_gate.py` — source-pin updated to the refactored helper
- `projects/polymarket/crusaderbot/tests/test_admin_console.py` — `_PRESET_PARAMS` roster-pin += candle_auto

Created:
- `projects/polymarket/crusaderbot/tests/test_candle_auto_router.py` — 8 hermetic tests

## 4. What is working

- Full PAPER pipeline: preset selectable on both surfaces → scanner router →
  per-rule entry → per-rule TP/SL on the position → per-rule force-exit at exit.
- Tests: 8 new router tests pass; full impacted sweep green —
  **2286 passed**, 0 related failures (the only 4 failures are pre-existing
  `ModuleNotFoundError: poly_eip712_structs` in `test_wallet_safe.py` /
  `test_builder_relayer.py`, unrelated to this lane). `ruff` clean; `py_compile`
  clean on all 6 modified production modules.
- No migration required (reuses `positions.strategy_metadata`, mig 076).
- No DB / activation-guard / risk-gate change. `_CANDLE_PRESETS` membership pin
  for the 3 single rules is preserved (separate `_ALL_CANDLE_PRESETS`).

## 5. Known issues

- **LIVE force-exit/TP-SL gap (documented, out of scope):** `domain/execution/live.py`
  does NOT persist `strategy_metadata` on the position INSERT (pre-existing — the
  weather strategy has the same gap). So on a LIVE position, `candle_auto`'s
  per-rule force-exit fallback has no stored value. The per-rule **TP/SL** still
  works in LIVE (it is persisted as `applied_tp_pct`/`applied_sl_pct`, not via
  metadata). Production is PAPER-only; this must be closed (add `strategy_metadata`
  to the live INSERT, fixing weather too) before the owner flips LIVE.
- **safe_close direction-concentration cap** (`_gate_safe_close_direction`) keys on
  `active_preset == "safe_close"`, so it does not apply to `candle_auto`'s
  safe-rule trades. Minor; the per-asset concentration sub-limit recommended in
  WARP-51 (H3) would supersede it.
- Combined-router EV is **UNMEASURED** (no backtest exists — WARP-51 F-1). Smart
  Strike blends three rules whose individual EV is unproven; treat paper results as
  the validation signal before any LIVE capital.

## 6. What is next

- WARP•SENTINEL validation (MAJOR tier) before merge.
- Paper-observe Smart Strike: confirm per-market single-rule routing, per-rule
  force-exits firing (flip holds to $1, safe exits rem30, close rem8), and that the
  30–35s overlap resolves to close_sweep.
- Pre-LIVE: close the `live.py` `strategy_metadata` gap (Known Issues #1).

---

### Validation Handoff (NEXT PRIORITY)
```
WARP•SENTINEL validation required for candle_auto router (Smart Strike) before merge.
Source: projects/polymarket/crusaderbot/reports/forge/candle-auto-router.md
Tier: MAJOR
```
