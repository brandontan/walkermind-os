# Runtime Config — Admin Overlay (Lane 1: strategy flags)

**Branch:** `WARP/ROOT/runtime-config-admin`
**Role:** WARP•R00T (owner-directed: "setting yang sering dipakai taruh di web admin, bukan Fly secret")
**Validation Tier:** STANDARD (runtime overlay; admin-gated; defaults to env, inert until used)
**Claim Level:** NARROW INTEGRATION (2 strategy master switches wired end-to-end)

> Owner directive: frequently-tuned bot settings should be editable from the web
> admin (DB-backed, no redeploy); Fly secrets only for global/rarely-changed +
> secrets. Decision locked: **start with strategy flags**, and **LIVE-trading
> guards stay Fly-secret-only** (NOT web-editable). This lane delivers the
> foundation + the two highest-value, single-read-site strategy switches.

## 1. What was built

A DB overlay over static (Fly/env) config, editable from the web admin:

- **`domain/ops/runtime_config.py`** (new) — `system_settings` overlay under the
  `cfg:` namespace. Precedence: **code default → env/Fly → DB override** (DB wins,
  whitelisted keys only). 30s TTL in-process cache (mirrors `kill_switch`).
  `resolve_bool` / `resolve_float` (fail-safe to env on missing/invalid/DB-error),
  validated `set_override` / `clear_override` (type + bounds; unknown key →
  `KeyError`, bad value → `ValueError`), and `list_effective` for the admin UI.
  Whitelist (`RUNTIME_SETTINGS`) is the ONLY surface: an unknown key can't be
  written or read, so the overlay can never shadow a secret or a LIVE guard.
- **Read-site conversion** — every *runtime* gate of the two flags now consults
  the overlay (falling back to the Fly/env value, so no override = unchanged):
  - `signal_scan_job.py` Phase B2 (`WEATHER_STRATEGY_ENABLED`) + Phase B3
    (`COMPLETE_SET_ARB_ENABLED`).
  - `domain/strategy/strategies/weather.py` — `scan()` and `evaluate_exit()` each
    had a SECOND static read that would otherwise short-circuit before the
    overlay took effect (caught in review); both now use the overlay so an admin
    can actually enable/disable weather without a redeploy.
  - `strategies/weather/strategy.py` — the standalone scheduler `scan_cycle()` +
    `monitor_cycle()` now guard on the overlay too, so toggling OFF stops that
    path at runtime as well.
- **`webtrader/backend/router.py`** + **`schemas.py`** — admin API:
  `GET /admin/settings` (effective values), `PATCH /admin/settings/{key}` (set),
  `DELETE /admin/settings/{key}` (revert to default). Admin-only (`_AdminUser`),
  rate-limited, audited (`admin_runtime_setting_update/clear`).
- **`webtrader/frontend`** — `lib/api.ts` client methods + `RuntimeSetting` type;
  AdminPage "Bot Settings (runtime — no redeploy)" section with a toggle per bool
  flag, an "● override" marker (DB vs env default), and a note that LIVE guards
  stay deploy-gated.

## 2. Architecture / safety

- **LIVE guards excluded by construction.** `ENABLE_LIVE_TRADING`,
  `EXECUTION_PATH_VALIDATED`, `CAPITAL_MODE_CONFIRMED` (and all secrets) are NOT in
  `RUNTIME_SETTINGS`, so they cannot be set or read through this path — a test
  pins this invariant. Turning on real capital still requires a deploy.
- **Fail-safe reads**: DB error / unparseable value / out-of-bounds → static env
  default (OFF for strategy flags). No override can silently widen behaviour.
- **No new table / migration**: reuses `system_settings` (mig 007). Keys are
  `cfg:`-namespaced so they never collide with kill-switch keys.
- **Incremental whitelist**: a key appears only once its read-site consults the
  overlay, so the admin UI never shows a toggle that does nothing.

## 3. Files created / modified

- `projects/polymarket/crusaderbot/domain/ops/runtime_config.py` (new)
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` (2 read-sites + import)
- `projects/polymarket/crusaderbot/webtrader/backend/router.py` (3 endpoints)
- `projects/polymarket/crusaderbot/webtrader/backend/schemas.py` (RuntimeSettingUpdate)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/lib/api.ts` (client + type)
- `projects/polymarket/crusaderbot/webtrader/frontend/src/pages/AdminPage.tsx` (panel)
- `projects/polymarket/crusaderbot/tests/test_runtime_config.py` (new — 14 tests)
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`, `CHANGELOG.md`

## 4. What is working

- 14 runtime_config tests pass: env-default fallback, DB-override-wins (both
  directions), invalid/non-whitelisted ignored, DB-error fail-safe, set/clear +
  read-back, unknown-key `KeyError`, bad-value `ValueError`, `list_effective`
  reporting, the secrets/guards-excluded invariant, and float bounds (forward).
- 159 touched-area tests pass (runtime_config + signal_scan_job + admin_console +
  kill_switch). `ruff` + `py_compile` clean. Frontend `tsc --noEmit` + `vite
  build` clean.

## 5. Known issues / scope boundaries

- **Lane 1 = 2 flags** (`WEATHER_STRATEGY_ENABLED`, `COMPLETE_SET_ARB_ENABLED`) —
  the two single-read-site strategy master switches. The other strategy flags
  (`FLIP_HUNTER_FAST_TOPUP_ENABLED`, `SAFE_CLOSE_IMBALANCE_OVERRIDE_ENABLED`,
  `CLOSE_SWEEP_DUAL_LEG_ENABLED`, `BANKROLL_CIRCUIT_BREAKER_ENABLED`) read at
  multiple sites and join in a follow-up lane as each site is converted.
- **Tuning thresholds** (`MIN_COMPLETE_SET_EDGE`, sizing caps) are a later lane —
  the float spec + bounds-enforced overlay are already built and tested.
- Propagation is per-process and TTL-bounded (~30s) — same model as kill switch.
- **Weather scheduler**: the standalone weather jobs in `scheduler.py` are now
  ALWAYS registered (was: only when the Fly flag was ON at startup) and each cycle
  self-guards on the overlay, so both ON and OFF take full effect at runtime with
  no redeploy. When disabled the cycle is a cheap no-op (cached flag check + early
  return). This closes the earlier registration caveat.

## 6. What is next

- **Follow-up lane A**: convert the remaining strategy-flag read-sites + add them
  to the whitelist.
- **Follow-up lane B**: tuning thresholds (`MIN_COMPLETE_SET_EDGE`, fast-topup
  knobs) with float editors in the admin panel (overlay already supports floats).
- **Follow-up lane C (separate, owner-gated)**: sizing caps with code hard-floors
  (override may only tighten) — `MAX_SINGLE_POSITION_PCT` / `MAX_TOTAL_EXPOSURE_PCT`
  / `MAX_DAILY_LOSS_USD`.

---

- **Validation Tier:** STANDARD
- **Claim Level:** NARROW INTEGRATION
- **Validation Target:** runtime_config overlay + 2 strategy-flag read-throughs + admin API/UI
- **Not in Scope:** remaining flags, tuning thresholds, sizing caps, LIVE guards (stay Fly-only)
- **Suggested Next Step:** WARP🔹CMD review → merge; then follow-up lanes A/B.
