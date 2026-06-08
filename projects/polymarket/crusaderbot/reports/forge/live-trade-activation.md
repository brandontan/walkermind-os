# WARP-92 — Two-Layer Live-Trade Activation (GLOBAL layer)

Branch: `WARP/live-trade-activation`
Role: WARP•FORGE
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: the net-new GLOBAL admin toggle (`global_live_trading_enabled`) — its cached reader, its hard-AND composition into the execution path, and the admin endpoint that flips it.
Not in Scope: the per-user live opt-in layer (already exists: WebTrader `POST /live/enable` + `domain/activation/live_opt_in_gate.py` + `live_checklist.py`); `ENABLE_LIVE_TRADING` env guard (read-only, never touched); `kill_switch`; `SCORER_ACTIVE`/`ORCHESTRATOR_ACTIVE`; risk/strategy domains.

---

## 1. What was built

WARP-92 adds **Condition 2** of the two-layer live-trade activation model: a single GLOBAL operator master switch that must be ON in addition to the env hard-stop and the existing per-user opt-in before any real order can route to the CLOB. It is seeded OFF and fail-safes to paper on every uncertainty.

Five pieces:

1. **Migration 091** — seeds `system_settings('global_live_trading_enabled','false')` (`ON CONFLICT DO NOTHING`). No schema change.
2. **`domain/ops/global_live_gate.py`** — cached (30s TTL) truthy reader `is_global_live_enabled()`, mirroring `kill_switch.py`. Missing key / any DB error → `False` (fail-safe to paper; NOT the kill-switch's fail-to-True). `invalidate_cache()` + `set_global_live(enabled)` writer that upserts and invalidates.
3. **`domain/execution/live_activation.py`** — pure read-only predicate `is_live_execution_allowed(user_id)` composing (in order, short-circuit AND): env `ENABLE_LIVE_TRADING`, global toggle, per-user (`trading_mode=='live'` AND `paper_mode_override is False` AND `live_capital_cap_usdc > 0`). Writes nothing.
4. **Executor hard gate** — `domain/execution/router.py execute()`: at the TOP of the `if chosen_mode == "live":` block, BEFORE `assert_live_guards`, a `if not await is_global_live_enabled():` pre-check that audits `live_blocked_fallback_paper` (reason `global_live_trading_disabled`) and routes to `_paper(...)`. Makes Condition 2 a hard AND → paper.
5. **Admin endpoint** — `api/admin.py` `PATCH /admin/settings/live-trading` (bearer `_check` pattern, like every `/admin` route): validates `{"enabled": bool}` (400 otherwise), reads prev value, upserts new value, calls `global_live_gate.invalidate_cache()`, audits via the EXISTING `write_mode_change_event(user_id=None, from_mode=prev, to_mode=new, reason=ADMIN_GLOBAL_TOGGLE)`. New enum member `ModeChangeReason.ADMIN_GLOBAL_TOGGLE = "admin_global_toggle"` (the only change to `live_opt_in_gate.py`).

## 2. Current system architecture

Live execution now requires THREE independent conditions, all AND-ed:

```
[1] ENABLE_LIVE_TRADING (env / Fly hard-stop)         — read-only
[2] global_live_trading_enabled (system_settings)     — NEW, admin toggle (Condition 2)
[3] per-user opt-in (user_settings: trading_mode/paper_mode_override/live_capital_cap_usdc)
                                                       — existing /live/enable + live_opt_in_gate
```

Enforcement points:
- `router.execute()` hard-gates on [2] before `assert_live_guards` (which already enforces [1] + role) → any failure routes to `_paper` with an audit row. This is the production hard gate.
- `is_live_execution_allowed()` composes [1]+[2]+[3] as a single read-only predicate for callers that want a pre-flight check (no writes, fail-safe to paper).

The cached reader means the per-call cost of [2] is one DB read per 30s TTL window, not per candidate.

## 3. Files created / modified (full repo-root paths)

Created:
- `projects/polymarket/crusaderbot/migrations/091_live_trade_activation.sql`
- `projects/polymarket/crusaderbot/domain/ops/global_live_gate.py`
- `projects/polymarket/crusaderbot/domain/execution/live_activation.py`
- `projects/polymarket/crusaderbot/tests/test_global_live_gate.py`
- `projects/polymarket/crusaderbot/tests/test_live_activation.py`
- `projects/polymarket/crusaderbot/tests/test_router_global_live_gate.py`
- `projects/polymarket/crusaderbot/tests/test_admin_global_live_toggle.py`

Modified:
- `projects/polymarket/crusaderbot/domain/execution/router.py` (import + global-flag pre-check in the live branch of `execute()`)
- `projects/polymarket/crusaderbot/api/admin.py` (new `PATCH /admin/settings/live-trading`)
- `projects/polymarket/crusaderbot/domain/activation/live_opt_in_gate.py` (added `ModeChangeReason.ADMIN_GLOBAL_TOGGLE` — single enum-member addition)
- `projects/polymarket/crusaderbot/tests/test_router_infra_fallback.py` (stub `is_global_live_enabled`→True in the shared `_wire` fixture so its downstream live-engine fallback tests still reach the live path past the new global gate)

## 4. What is working

- `pytest projects/polymarket/crusaderbot/tests/ -q` → **3136 passed, 15 skipped, 4 failed**. The 4 failures are the pre-existing, unrelated `test_clob_pysdk.py` cases (missing optional `polymarket` module) noted in the directive. No other failures.
- `ruff check .` → **All checks passed!**
- New coverage: truthy/falsey parse, missing-key→False, DB-error→False (not cached), TTL cache, cache invalidation, write+invalidate (global gate); all six AND conditions of `is_live_execution_allowed` independently falsified + the all-pass True case; router routes to paper + audits when global flag False and proceeds to `assert_live_guards`/live engine when True (no regression); admin PATCH 400 on non-bool, upsert + cache invalidate + `write_mode_change_event(reason=ADMIN_GLOBAL_TOGGLE, user_id=None)`.
- Migration seeds `'false'` → live is never enabled by default. Admin write invalidates the cache so an operator flip is reflected immediately on the handling process. Audit reuses the existing `mode_change_events` writer (no schema change — `reason` has no CHECK constraint, `user_id` is nullable).

## 5. Known issues

- None functional. The global flag has a ≤30s propagation window across other processes (the in-process cache TTL), identical to the kill switch — acceptable and documented. The single-process Fly deployment shares one event loop so the admin-write invalidate is effectively immediate in prod.
- `is_live_execution_allowed()` is a ready-to-use composition predicate but is not yet wired into any caller (the production hard gate lives in `router.execute()`); wiring it as a pre-flight check at candidate sources is a possible follow-up, not required for Condition 2.

## 6. What is next

- WARP•SENTINEL MAJOR validation (live-trading lane) before any merge.
- After merge + deploy: migration 091 applies via CD; the flag stays `'false'` until an operator explicitly `PATCH /admin/settings/live-trading {"enabled": true}` (which, combined with the env guard and a per-user opt-in, is the only path to live).

Suggested Next Step: WARP•SENTINEL validation of the global activation layer (executor hard-gate + admin toggle + fail-safe direction), then WARP🔹CMD merge decision. This lane delivers the GLOBAL layer ONLY — the per-user layer remains the existing `/live/enable` + `live_opt_in_gate` (no duplication).
