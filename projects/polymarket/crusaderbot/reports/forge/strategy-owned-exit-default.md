# WARP•R00T FORGE REPORT — strategy-owned-exit-default (WARP-85 Phase 0)

Branch: `WARP/strategy-owned-exit-default`
Role: WARP•R00T (owner-authorized 2026-06-08 — "Option 1: align hooks to 150/50, then rewire")
Validation Tier: **STANDARD** (TP/SL default source rewire; crypto runtime byte-identical, no risk/gate/capital change)
Claim Level: NARROW INTEGRATION
Validation Target: The defensive TP/SL default applied when `user_settings.tp_pct/sl_pct` is NULL is resolved FROM the active strategy's `default_tp_sl()` hook (STRATEGY stage), not the hardcoded scan-job module constant — with crypto/late_entry_v3 net behavior byte-identical (1.5/0.5).
Not in Scope: risk-profile decoupling beyond TP/SL ownership; per-profile EV calibration; SCORER/ORCHESTRATOR flips; exit_watcher / TP-SL exit math; UI; migrations; presets; config keys.
Suggested Next Step: WARP🔹CMD review + merge. No deploy verification needed beyond confirming the candle path still resolves 1.5/0.5 (regression-pinned); the fallback only fires on legacy/NULL rows (089 backfilled all prod rows), so steady-state runtime is unchanged.

---

## 1. What was built

WARP-85 Phase 0 makes the E.2 interim baseline architecturally correct. Exit
thresholds (TP/SL) are a **STRATEGY-stage** concern per the CLAUDE.md SYSTEM
PIPELINE (`DATA -> STRATEGY -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING`);
the risk profile is a RISK-stage exposure/sizing concern only. Before this lane,
the user_settings-NULL fallback in `signal_scan_job._build_trade_signal` came
from a module constant (`_DEFAULT_STRATEGY_TP_PCT/SL_PCT = 1.5/0.5`) living in
the scan-job service — a pipeline-boundary violation: the default must come FROM
the strategy.

Now:
- `_build_trade_signal` resolves the default via a new module helper
  `_strategy_default_tp_sl(strategy_name)` →
  `StrategyRegistry.instance().get(name).default_tp_sl()`.
- The module constants `_DEFAULT_STRATEGY_TP_PCT/SL_PCT` were removed and
  replaced by a single, clearly-commented **last-resort guard**
  (`_LAST_RESORT_TP_PCT/SL_PCT = 1.5/0.5`) used ONLY when no strategy can be
  resolved (registry miss / malformed hook return) — logged, never silent, never
  the normal path.
- `user_settings.tp_pct/sl_pct` still wins LITERALLY when present (E.2 invariant
  preserved); the strategy hook is the fallback source only.

### STOP-condition + owner ruling
The task assumed the active crypto strategy's `default_tp_sl()` already returned
(1.5, 0.5). It did NOT: `late_entry_v3.default_tp_sl()` returned **0.15/0.08**
(stale "close_sweep" doc value, never runtime-exercised) and
`signal_following` returned **0.20/0.08** — neither matched the live E.1/E.2
Balanced baseline (1.5/0.5) that migration 089 backfilled into every
`user_settings` row. Routing the fallback through the hook as-is would have
silently changed the cold-path default ~10× (a hard Stop Condition). Surfaced to
the owner; owner authorized **Option 1**: align both hooks to the proven
1.5/0.5 baseline (15/8 was a stale unvalidated default), then rewire — keeping
crypto runtime byte-identical.

## 2. Current system architecture

`_build_trade_signal` (scan-job) now depends on the STRATEGY plane for its exit
default:

```
user_settings.tp_pct/sl_pct present? --(yes)--> use it LITERALLY  (E.2 source of truth)
                                     --(no)---> _strategy_default_tp_sl(cand.strategy_name)
                                                  └─> StrategyRegistry.get(name).default_tp_sl()
                                                       └─(unresolvable)─> _LAST_RESORT_* (logged)
```

Strategy-owned default value (`default_tp_sl()`) is now uniform across the
enabled strategies at the E.1/E.2 Balanced baseline (1.5/0.5). RISK-stage code
(`domain/risk/*`) is untouched — exposure/sizing only.

## 3. Files created / modified (full repo-root paths)

- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` — removed `_DEFAULT_STRATEGY_TP_PCT/SL_PCT`; added `_LAST_RESORT_TP_PCT/SL_PCT` + `_strategy_default_tp_sl()`; rewired `_build_trade_signal` fallback to the strategy hook (logs now carry `strategy_name`).
- `projects/polymarket/crusaderbot/domain/strategy/strategies/late_entry_v3.py` — `DEFAULT_TP_PCT/SL_PCT` 0.15/0.08 → 1.5/0.5; docstring updated.
- `projects/polymarket/crusaderbot/domain/strategy/strategies/signal_following.py` — `DEFAULT_TP_PCT/SL_PCT` 0.20/0.08 → 1.5/0.5; docstring updated.
- `projects/polymarket/crusaderbot/tests/test_strategy_owned_exit_default.py` (new) — 9 tests (resolver hook/last-resort, end-to-end builder, crypto byte-identical regression, user_settings override, removed-constants guard).
- `projects/polymarket/crusaderbot/tests/test_honest_tpsl_controls.py` — fallback assertions repointed to `_LAST_RESORT_*` (value unchanged 1.5/0.5).
- `projects/polymarket/crusaderbot/tests/test_fast_track_a.py` — same repoint.
- `projects/polymarket/crusaderbot/tests/test_late_entry_v3.py` — default_tp_sl spec 0.15/0.08 → 1.5/0.5.
- `projects/polymarket/crusaderbot/tests/test_signal_following.py` — default_tp_sl spec 0.20/0.08 → 1.5/0.5.
- state: `state/PROJECT_STATE.md`, `state/CHANGELOG.md`.

## 4. What is working

- Crypto/late_entry_v3 fallback resolves to (1.5, 0.5) — byte-identical regression (`test_resolver_crypto_is_byte_identical`, `test_null_settings_crypto_resolves_to_150_50`).
- Default provably flows FROM `default_tp_sl()` — a stub strategy with sentinel default (0.77/0.11) drives the built signal (`test_null_settings_default_flows_from_strategy_hook`).
- `user_settings` literal value still overrides the strategy default (`test_user_settings_literal_overrides_strategy_default`) — E.2 invariant intact.
- Last-resort guard fires + logs when the strategy is unresolvable (`test_resolver_last_resort_when_unresolvable`).
- Full suite: **3054 passed**, 9 skipped; the 14 failures are pre-existing/environmental (missing optional SDKs `poly_eip712_structs`/relayer, DB-pool-not-initialised) — confirmed identical on the base branch with changes stashed. ruff clean.

## 5. Known issues

- None introduced. The strategy `default_tp_sl()` hooks are now uniform (1.5/0.5); if a future strategy genuinely needs a different default, it sets its own hook — the scan job no longer hardcodes one.
- `test_phase5g_customize_wizard.py` still uses 0.15/0.08 as user-entered custom-wizard inputs — those are user values, NOT the strategy default, and are intentionally untouched (out of scope).

## 6. What is next

WARP🔹CMD review + merge. Phase boundaries beyond TP/SL ownership (risk-profile
decoupling, per-profile EV calibration) remain deferred to later lanes per the
task scope.

---

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: TP/SL default sourced from `default_tp_sl()`; crypto byte-identical (1.5/0.5); user_settings literal preserved.
Not in Scope: domain/risk/*, webtrader/*, migrations/*, presets, config, exit_watcher, EV calibration, SCORER/ORCHESTRATOR flips.
Suggested Next Step: WARP🔹CMD review + merge.
