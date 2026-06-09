# WARP•FORGE — honest-tpsl-controls (WARP-83 Sub-Lane E.2, Path C)

Validation Tier: MAJOR
Claim Level: FULL RUNTIME INTEGRATION
Validation Target: TP/SL sourcing across the late-entry/candle scan entry path
(signal_scan_job), the risk-profile / preset-activation backend, the risk-profile
UI cards, and the backfill migration (089). Confirms `user_settings.tp_pct/sl_pct`
is the single source of truth the strategy reads at entry, with a logged
defensive fallback, and that no existing position's `applied_tp_pct/applied_sl_pct`
is altered.
Not in Scope: ev_comparator / scorer / scorer_trainer; orchestrator; the §1.7
paper verdict; the playbook (sports) strategy's own metadata TP/SL; live-DB
migration application; fast_topup / safe_close secondary builder paths (they
already read user_settings directly and are not the deception path — see Known
issues); exit-watcher math.

---

## 1. What was built

The fix for the UX-deception bug where `user_settings.tp_pct/sl_pct` were
silently ignored and the strategy applied a hardcoded / per-rule / per-profile
TP/SL (e.g. 150%/50% from the flip rule, or 10%/5% from the Conservative
profile) regardless of the user's UI configuration.

Path C semantics implemented exactly:
- Risk profile = CAPITAL SIZING ONLY (`capital_alloc_pct` + `max_position_pct`).
- TP/SL = STRATEGY-LEVEL property = Balanced 150% / 50% for everyone by default.
- `user_settings.tp_pct/sl_pct` is now the SOURCE OF TRUTH the strategy reads.
- Conservative = SAME TP/SL as Balanced (1.5/0.5), only smaller capital — it
  "risks fewer dollars, it does not exit faster". No Conservative or Aggressive
  TP/SL bundle was created.

Changes:
1. Strategy entry path (`signal_scan_job._build_trade_signal`) now resolves TP/SL
   from `user_settings.tp_pct/sl_pct` LITERALLY, with a logged defensive fallback
   to the strategy default (1.5/0.5) when the column is NULL/missing.
2. The `candle_auto` lifecycle router no longer stamps per-rule
   `applied_tp_pct/applied_sl_pct` into candidate metadata (this stamp was the
   override that beat user_settings). The dead `_candle_auto_rule_tpsl` helper was
   removed.
3. The risk-profile / preset-activation backend now seeds `user_settings` TP/SL
   with the strategy default (1.5/0.5) for ALL non-custom profiles via the
   canonical `PROFILE_TP_SL` (single source of truth, capital still per-profile).
4. Risk-profile UI cards display TP/SL as INFORMATIONAL strategy-level values
   (same for every profile), keep per-profile capital, and the Custom Risk
   block is the advanced override path with an explicit "not backtested" warning.
5. Telegram TP/SL is unchanged in code but now correct: it consumes the
   `position.opened` event whose `tp_pct/sl_pct` = `signal.tp_pct/sl_pct`, which
   is now the user_settings value.
6. Backfill migration 089 + rollback set every `user_settings` row to 1.5/0.5
   so the pre-existing 150/50 behaviour is preserved when the new code reads
   user_settings. `positions` is never touched.

The exact hardcode that lived at
`projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
(candle_auto router stamping per-rule preset TP/SL, e.g. flip_hunter 1.5/0.5,
into `metadata["applied_tp_pct"]/["applied_sl_pct"]`, which then overrode
user_settings in `_build_trade_signal`) was removed; the builder now reads
user_settings with a logged fallback.

## 2. Current system architecture

Entry path (unchanged stages, corrected TP/SL sourcing):

```
DATA -> STRATEGY (late_entry_v3 / candle_auto router) -> INTELLIGENCE -> RISK -> EXECUTION -> MONITORING
```

- `signal_scan_job` SQL selects `s.tp_pct, s.sl_pct` from `user_settings`.
- `_scan_late_entry_for_preset` (candle_auto branch) stamps only exit-TIMING
  metadata (`candle_rule`, force-exit via scan()) — NO TP/SL bundle.
- `_build_trade_signal` resolves `tp_pct/sl_pct` from the user_settings row, with
  a logged defensive fallback to `_DEFAULT_STRATEGY_TP_PCT/SL_PCT` (1.5/0.5).
- `TradeEngine.execute` writes `signal.tp_pct/sl_pct` to
  `positions.applied_tp_pct/applied_sl_pct` at INSERT (entry-time snapshot,
  immutable per migration 005 trigger + registry boundary).
- Profile/preset activation backend seeds user_settings TP/SL = strategy default
  (1.5/0.5) for non-custom profiles via canonical `PROFILE_TP_SL`; capital stays
  per-profile.

Deploy ordering (load-bearing): `main.lifespan` runs
`init_pool() -> run_migrations() -> scheduler/scan start`, so migration 089
backfills `user_settings` BEFORE the new `_build_trade_signal` code reads it.
Net runtime behaviour is preserved across the deploy.

## 3. Files created / modified (full repo-root paths)

Created:
- projects/polymarket/crusaderbot/migrations/089_backfill_user_settings_tpsl.sql
- projects/polymarket/crusaderbot/migrations/rollback/089_backfill_user_settings_tpsl_rollback.sql
- projects/polymarket/crusaderbot/tests/test_honest_tpsl_controls.py

Modified:
- projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py
- projects/polymarket/crusaderbot/domain/risk/constants.py
- projects/polymarket/crusaderbot/webtrader/backend/router.py
- projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AutoTradePage.tsx
- projects/polymarket/crusaderbot/tests/test_candle_auto_router.py
- projects/polymarket/crusaderbot/tests/test_tpsl_from_profile.py
- projects/polymarket/crusaderbot/tests/test_fast_track_a.py
- projects/polymarket/crusaderbot/state/PROJECT_STATE.md
- projects/polymarket/crusaderbot/state/CHANGELOG.md

## 4. What is working

- New + modified Python tests: 77 passed across
  test_honest_tpsl_controls.py (17), test_candle_auto_router.py,
  test_tpsl_from_profile.py, test_fast_track_a.py.
  `python -m pytest <files> -q` => 77 passed.
- ruff check clean on all changed Python files.
- py_compile clean on signal_scan_job.py, constants.py, router.py.
- Strategy reads user_settings TP/SL literally (test_strategy_reads_user_settings_tpsl_literally).
- Defensive fallback to 1.5/0.5 on NULL, logged (test_defensive_fallback_when_tpsl_null / partial).
- candle_auto router no longer stamps applied_tp_pct/applied_sl_pct
  (test_router_merges_dedups_and_stamps asserts absence).
- Profile activation seeds 1.5/0.5 for all non-custom profiles; Conservative
  keeps same TP/SL as Balanced but smaller capital
  (test_conservative_same_tpsl_as_balanced_but_smaller_capital).
- Migration 089 is idempotent-shaped (guarded UPDATE, IS DISTINCT FROM), has a
  rollback, and touches only user_settings — never positions / applied_*
  (test_migration_089_never_touches_positions, test_rollback_089_never_touches_positions).
- Custom Risk advanced override path writes user_settings via the existing
  auth-gated `api.setRiskProfile` and now carries an explicit "non-default values
  are not backtested" warning.

## 5. Known issues

- Frontend was not type-checked / built in this environment (no node_modules;
  installing the full Vite/TS toolchain was out of scope for a dep-light
  sandbox). The TSX edits were verified by source inspection: the new
  `STRATEGY_TP_PCT/STRATEGY_SL_PCT` constants are defined and used consistently,
  and no stale `rp.tp/rp.sl` references remain after removing those fields from
  RISK_PROFILES. WARP•SENTINEL should run `npm run build` (tsc) to confirm.
- The secondary builder paths `fast_topup` and `safe_close` in signal_scan_job
  already read `user_settings.tp_pct/sl_pct` directly (no metadata override) so
  they are NOT the deception path; they were intentionally left to pass `None`
  when the column is NULL rather than adding the same defensive fallback. After
  migration 089 no NULLs exist, so this is benign. Flagged for awareness.
- Rollback 089 is best-effort/non-lossless: 089 overwrote prior per-row values
  with the strategy default, so the rollback restores the prior COLUMN DEFAULTS
  (0.90/0.40), not the exact pre-089 per-user values. Documented in the rollback
  file header.
- Migration 089 was authored only — NOT applied to the live DB (per scope). The
  user_settings schema was verified read-only via Supabase MCP (project
  ykyagjdeqcgcktnpdhes): tp_pct numeric nullable default 0.90, sl_pct numeric
  nullable default 0.40, capital_alloc_pct numeric NOT NULL default 0.40,
  max_position_pct numeric nullable, risk_profile varchar NOT NULL.

## 6. What is next

- WARP•SENTINEL MAJOR validation (entry-path TP/SL sourcing, defensive fallback,
  no-retroactive-position guarantee, migration idempotency/rollback, frontend
  tsc build, deploy-ordering review).
- On approval: apply migration 089 to the live DB BEFORE / as part of the deploy
  (CD runs run_migrations at boot ahead of scan start), then merge.

---

Suggested Next Step: WARP•SENTINEL validation required for E.2 (MAJOR) before
merge — Source:
projects/polymarket/crusaderbot/reports/forge/honest-tpsl-controls.md
