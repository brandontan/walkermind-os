# WARP-50b — Replace access_tier with role-based access model

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: All production files referencing `access_tier` for access gating — gating logic replaced with `users.role` column ('admin' | 'user'). `access_tier` column itself stays in DB; migration 044 (DROP) deferred.
Not in Scope: DB schema DROP (044), frontend, new features, refactor of `services/tiers.py` (string `user_tiers` system — separate from `access_tier`).
Suggested Next Step: WARP🔹CMD review → merge. Run `045_add_role_column.sql` against staging before merging. Once stable, schedule a follow-up lane to apply `044_drop_access_tier.sql`.

---

## 1. What was built

- All access gating moved from the integer `users.access_tier` column to a two-value `users.role` column (`'admin'` | `'user'`).
- Paper trading is open to every user (no role check anywhere in the paper path).
- Live trading and admin tooling now check `role == 'admin'` instead of `access_tier >= 4`.
- Legacy `access_tier` column is left intact in the schema and explicitly set to `4` on all new INSERTs so the NOT NULL constraint does not break. Removal stays staged behind `044_drop_access_tier.sql`.
- New migration `045_add_role_column.sql` adds the column with default `'user'` and promotes the earliest-created user to `'admin'` if no admin exists yet.

## 2. Current system architecture

```
INSERT path (users.py / user_service.py / scripts/seed_*)
    └─> users (telegram_user_id, username, access_tier=4, role='user'|'admin')

Access gating
    ├─ paper trading       : open to all users (no decorator, no SQL filter)
    ├─ admin Telegram cmds : @require_role('admin') from bot/middleware/access_tier.py
    ├─ live risk gate      : domain/risk/gate.py — ctx.role == 'admin' (step 3 + _passes_live_guards)
    ├─ live order submit   : domain/execution/live.assert_live_guards(role, trading_mode)
    └─ live checklist [8]  : domain/activation/live_checklist._gate_operator_allowlist — SELECT role

ctx propagation
    scheduler.run_signal_scan   ─┐
    signal_scan_job._build_*    ─┼─> TradeSignal.role ─> GateContext.role ─> router.execute(role=…)
    copy_trade.monitor          ─┘                                          └─> live.assert_live_guards(role, mode)

Operator seeding
    scripts/seed_operator_tier  ─> users.role = 'admin' (idempotent upsert, prev role audited)
```

## 3. Files created / modified (full repo-root paths)

Created:

- `projects/polymarket/crusaderbot/migrations/045_add_role_column.sql`
- `projects/polymarket/crusaderbot/reports/forge/fix-access-tier-open-warp50b.md`

Modified — production:

- `projects/polymarket/crusaderbot/users.py`
- `projects/polymarket/crusaderbot/services/user_service.py`
- `projects/polymarket/crusaderbot/services/tiers.py` (docstring only — module is the parallel string-tier system and untouched)
- `projects/polymarket/crusaderbot/bot/middleware/access_tier.py`
- `projects/polymarket/crusaderbot/domain/risk/gate.py`
- `projects/polymarket/crusaderbot/domain/activation/live_checklist.py`
- `projects/polymarket/crusaderbot/domain/execution/live.py`
- `projects/polymarket/crusaderbot/domain/execution/router.py`
- `projects/polymarket/crusaderbot/domain/execution/parity.py`
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py`
- `projects/polymarket/crusaderbot/scheduler.py`
- `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py`
- `projects/polymarket/crusaderbot/services/copy_trade/monitor.py`
- `projects/polymarket/crusaderbot/api/admin.py`
- `projects/polymarket/crusaderbot/scripts/seed_demo_data.py`
- `projects/polymarket/crusaderbot/scripts/seed_operator_tier.py`

Modified — tests:

- `projects/polymarket/crusaderbot/tests/test_access_tiers.py`
- `projects/polymarket/crusaderbot/tests/test_isolation_audit.py`
- `projects/polymarket/crusaderbot/tests/test_live_checklist.py`
- `projects/polymarket/crusaderbot/tests/test_live_execution_rewire.py`
- `projects/polymarket/crusaderbot/tests/test_seed_operator_tier.py`
- `projects/polymarket/crusaderbot/tests/test_fast_track_a.py`
- `projects/polymarket/crusaderbot/tests/test_pipeline_runtime_hardening.py`
- `projects/polymarket/crusaderbot/tests/test_fallback.py`

## 4. What is working

- `python3 -m compileall` on every modified production file: clean.
- Full pytest suite: `1512 passed, 24 warnings` (0 failed).
- `assert_live_guards(role='admin', trading_mode='live')` accepts admin only; `role='user'` raises `LivePreSubmitError("role='user' not admin")`.
- `require_role('admin')` decorator blocks non-admin Telegram users and replies "Admin access required."; `require_role('user')` is open.
- `_gate_operator_allowlist` reads `SELECT role FROM users WHERE id=$1` and passes iff role='admin'.
- Risk gate step 3 enforces `role == 'admin'` only when `trading_mode == 'live'`; paper mode is unconditional pass.
- Scheduler + signal_scan_job + copy_trade monitor all SELECT `u.role` and propagate it to `GateContext.role` / `TradeSignal.role`.
- `seed_operator_tier` idempotently upserts `role='admin'` (with `access_tier=4` placeholder); existing-admin path is a no-op; user→admin path emits an `operator_role_seed` audit row with `prev_role`/`new_role`.

## 5. Known issues

- `access_tier` column is still present and is set to a constant `4` on every INSERT. This is intentional — removal is staged behind `044_drop_access_tier.sql`, which is to be applied as a separate lane after this PR is stable in production. Until then the column is dead-write data.
- `users.set_tier` / `users.force_set_tier` remain in `users.py` so existing admin tooling (`bot/handlers/admin.py:allowlist_command`) that writes `access_tier` still functions, but those writes no longer gate anything — admin promotion now requires `users.set_role(user_id, 'admin')` (also new in this lane).
- `services/tiers.py` (the `user_tiers` string-tier table) is unchanged. It is a parallel system that predates the role model; the docstring was updated to call this out. Cleanup is a separate lane.

## 6. What is next

1. Apply `045_add_role_column.sql` on staging.
2. WARP🔹CMD review of this PR.
3. After merge + stable production window, open a follow-up lane to:
   - Apply `044_drop_access_tier.sql` and remove every remaining write of `access_tier=4` in INSERT statements.
   - Replace `users.set_tier` / `users.force_set_tier` / `bot/handlers/admin.py:allowlist_command` with the role-based equivalent.
   - Decide the fate of `services/tiers.py` (`user_tiers` table).
