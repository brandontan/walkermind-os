# WARP-51 — Drop access_tier column + full Python cleanup

Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Validation Target: Every `.py` writer/reader of the `access_tier` column removed; migration `044_drop_access_tier.sql` re-enabled and ready to apply on next Fly deploy; pytest 1487 passed.
Not in Scope: Live trading activation, execution / risk pipeline changes, frontend, `services/tiers.py` (parallel `user_tiers` string-tier system stays), `bot/middleware/access_tier.py` (file kept under that name for import-path stability — content is role-based since WARP-50b).
Suggested Next Step: WARP•SENTINEL audit on the validation target above. After merge: Fly redeploy runs `044_drop_access_tier.sql` via `run_migrations()`.

---

## 1. What was built

- Stripped `access_tier` from every production INSERT, SELECT, RETURNING, and UPDATE path.
- Deleted the two obsolete `set_tier()` / `force_set_tier()` helpers from `users.py`; the only remaining writer to user access state is `set_role(user_id, 'admin' | 'user')`.
- Converted `/allowlist` admin command (`bot/handlers/admin.py:allowlist_command`) from `force_set_tier(user_id, tier)` to `set_role(user_id, 'admin')` — same audit row, new payload `{"new_role": "admin"}`.
- Deleted `scripts/seed_operator_tier.py` and its test `tests/test_seed_operator_tier.py`. Removed the corresponding `[deploy].release_command` line from `fly.toml`.
- Cleaned `scripts/seed_demo_data.py` INSERT to write `role` only.
- Re-enabled migration `044_drop_access_tier.sql` (was `.disabled` after the post-merge crash-loop hotfix in PR #1223). Header updated to document the WARP-51 re-enable.
- Swept 15 test files: dropped dead `"access_tier"` keys from user fixtures and `access_tier: int` parameters from fixture builders. Test count 1512 → 1487 (delta = 24 deleted `test_seed_operator_tier.py` tests + 1 environmental skip).
- Updated `docs/runbooks/kill-switch-procedure.md` to reflect that `ADMIN_USER_IDS` is no longer consumed by an automated deploy seeder; admin promotion now runs via `/allowlist` at runtime.

## 2. Current system architecture (relevant slice)

```
INSERT path (users.py / services/user_service.py / scripts/seed_demo_data.py)
    └─> users (telegram_user_id, username, role='user', ...)
                                            └─ no access_tier write, no placeholder

Admin promotion
    Telegram /allowlist  ─> bot/handlers/admin.py:allowlist_command
                            └─> users.set_role(user_id, 'admin')
                                └─> UPDATE users SET role='admin' WHERE id=$1
                                + audit.log(action='allowlist', payload={'new_role':'admin'})

Access gating (unchanged since WARP-50b)
    ├─ paper trading       : open to all users (no decorator, no SQL filter)
    ├─ admin Telegram cmds : @require_role('admin') from bot/middleware/access_tier.py
    ├─ live risk gate      : domain/risk/gate.py — ctx.role == 'admin'
    ├─ live order submit   : domain/execution/live.assert_live_guards(role, mode)
    └─ live checklist [8]  : domain/activation/live_checklist._gate_operator_allowlist

Migration path (next Fly deploy)
    run_migrations()  ─> 044_drop_access_tier.sql
                          └─> ALTER TABLE users DROP COLUMN IF EXISTS access_tier;
```

## 3. Files created / modified (full repo-root paths)

Modified — production code:

- `projects/polymarket/crusaderbot/users.py` (INSERT cleaned; `set_tier` / `force_set_tier` deleted)
- `projects/polymarket/crusaderbot/services/user_service.py` (INSERT + SELECT + RETURNING + docstring cleaned)
- `projects/polymarket/crusaderbot/services/tiers.py` (docstring — removed access_tier file path)
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` (`/allowlist` converted to `set_role('admin')`; import swapped)
- `projects/polymarket/crusaderbot/api/admin.py` (`funded` comment cleaned)
- `projects/polymarket/crusaderbot/scripts/seed_demo_data.py` (demo user INSERT cleaned)

Modified — config / infra:

- `projects/polymarket/crusaderbot/fly.toml` (deleted `release_command`)
- `projects/polymarket/crusaderbot/migrations/044_drop_access_tier.sql` (renamed from `.disabled`; header rewritten)
- `projects/polymarket/crusaderbot/docs/runbooks/kill-switch-procedure.md` (ADMIN_USER_IDS narrative updated)

Modified — tests (fixture sweep):

- `projects/polymarket/crusaderbot/tests/test_access_tiers.py` (docstring)
- `projects/polymarket/crusaderbot/tests/test_activation_handlers.py`
- `projects/polymarket/crusaderbot/tests/test_copy_trade.py`
- `projects/polymarket/crusaderbot/tests/test_fast_track_b.py`
- `projects/polymarket/crusaderbot/tests/test_live_opt_in_gate.py`
- `projects/polymarket/crusaderbot/tests/test_phase5d_grid_menu_split.py`
- `projects/polymarket/crusaderbot/tests/test_phase5e_copy_trade.py`
- `projects/polymarket/crusaderbot/tests/test_phase5f_copy_wizard.py`
- `projects/polymarket/crusaderbot/tests/test_phase5g_customize_wizard.py`
- `projects/polymarket/crusaderbot/tests/test_phase5h_onboarding.py`
- `projects/polymarket/crusaderbot/tests/test_phase5j_emergency.py`
- `projects/polymarket/crusaderbot/tests/test_portfolio_charts_insights.py`
- `projects/polymarket/crusaderbot/tests/test_preset_system.py`
- `projects/polymarket/crusaderbot/tests/test_signal_following.py`
- `projects/polymarket/crusaderbot/tests/test_signal_scan_job.py`
- `projects/polymarket/crusaderbot/tests/test_users.py`

Deleted:

- `projects/polymarket/crusaderbot/scripts/seed_operator_tier.py`
- `projects/polymarket/crusaderbot/tests/test_seed_operator_tier.py`

Renamed:

- `projects/polymarket/crusaderbot/migrations/044_drop_access_tier.sql.disabled` → `projects/polymarket/crusaderbot/migrations/044_drop_access_tier.sql`

Created:

- `projects/polymarket/crusaderbot/reports/forge/warp51-drop-access-tier.md`

## 4. What is working

- `python3 -m compileall projects/polymarket/crusaderbot`: clean.
- `python3 -m pytest projects/polymarket/crusaderbot/tests/ -q`: **1487 passed, 1 skipped, 0 failed**.
- `grep -RnE "access_tier" --include="*.py" projects/polymarket/crusaderbot/` returns only file-path references to the kept `bot/middleware/access_tier.py` module (no remaining column-name references in code).
- `/allowlist @user` now promotes a user to `role='admin'` via `set_role()`, audit log entry `action='allowlist'` with payload `{"new_role": "admin"}`.
- Migration `044_drop_access_tier.sql` is back in the `*.sql` glob and will execute on next Fly deploy. INSERT path no longer references the column, so the DROP cannot recreate the WARP-50b crash loop.
- `assert_live_guards`, `require_role('admin')`, and the risk-gate `ctx.role == 'admin'` checks are unchanged — paper open to all, live owner-gated. Activation guards remain OFF.

## 5. Known issues

- `bot/middleware/access_tier.py` keeps its filename for import-path stability per WARP🔹CMD instruction. Body is fully role-based (`require_role` + `_get_role`); only the filename retains the historical token. A future rename to `bot/middleware/role_guard.py` is possible but explicitly out of scope here.
- `services/tiers.py` (the `user_tiers` string-tier system) is unchanged. It is a parallel module that pre-dates the role model and is not part of `users.access_tier`. Decision on its fate is a separate lane.
- `bot/tier.py` still defines the legacy `Tier` integer enum (`BROWSE=1, ALLOWLISTED=2, FUNDED=3, LIVE=4`). The enum is no longer read by any production gating path (the matching call sites were stripped earlier in WARP-50b). Removal is a follow-up cleanup, deferred to keep WARP-51 scope-bound.
- Migration 044 applies on the next Fly deploy after merge — until that deploy runs, the production `users.access_tier` column physically exists with the placeholder value `4` on every row. Code no longer reads it.

## 6. What is next

1. WARP•SENTINEL audit:
   - Verify zero `access_tier` column references in `.py` code (file-path refs to `bot/middleware/access_tier.py` are expected).
   - Verify `044_drop_access_tier.sql` is in glob (no `.disabled`).
   - Verify pytest 1487+ passed.
   - Verify `set_role` is the only path that writes elevated user state.
   - Verify live-trading guard surfaces (`assert_live_guards`, risk gate, live checklist) unchanged.
2. WARP🔹CMD merge.
3. Fly redeploy — `run_migrations()` executes `044_drop_access_tier.sql` automatically.
4. Optional follow-up lanes (not in WARP-51):
   - Rename `bot/middleware/access_tier.py` → `bot/middleware/role_guard.py`.
   - Remove legacy `bot/tier.py` integer enum.
   - Decide on `services/tiers.py` + `user_tiers` table.
