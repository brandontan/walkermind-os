# WARP•FORGE Report — copy-task-repo-returning-fix

Branch: WARP/copy-task-repo-returning-fix
Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: domain/copy_trade/repository.py create_task + update_task RETURNING clauses
Not in Scope: copy-trade monitor pipeline, wallet_watcher, Phase C signal feed

---

## 1. What was built

Fixed a `KeyError` bug in `domain/copy_trade/repository.py` that caused every Telegram copy-task creation and update to fail silently.

**Root cause**: `create_task()` and `update_task()` had RETURNING clauses that omitted 4 columns added by migration 035: `nickname`, `copy_direction`, `execution_mode`, `allow_topups`. `_row_to_task()` accessed those 4 columns unconditionally via `row["nickname"]` etc., raising `KeyError` on every call from the Telegram copy-trade wizard (`bot/handlers/copy_trade.py:1122`).

**Impact**:
- Every Telegram copy-task creation failed at the exception handler (line 1135), showing "❌ Could not create task" and returning without writing to DB
- `list_active_tasks()` was unaffected (it uses `_SELECT` with `COALESCE` — correct)
- `CopyTradeMonitor` ran but found 0 active tasks → 0 copy-trade positions
- This is the direct code cause of F-HIGH-2 for users with `active_preset = 'whale_mirror'`

**Fix**: Added the 4 missing columns to the RETURNING clauses of `create_task` and `update_task`, using `COALESCE` for the columns with DB defaults (same pattern as `_SELECT`).

---

## 2. Current system architecture

```
Telegram copy-task wizard (bot/handlers/copy_trade.py)
  └─ repo.create_task() → domain/copy_trade/repository.py
       └─ INSERT INTO copy_trade_tasks ... RETURNING [...all 4 columns now included...]
  └─ repo.update_task() → domain/copy_trade/repository.py
       └─ UPDATE copy_trade_tasks ... RETURNING [...all 4 columns now included...]
       
CopyTradeMonitor.run_once()
  └─ list_active_tasks() → was unaffected, reads canonical copy_trade_tasks
```

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/domain/copy_trade/repository.py`
  - `create_task` RETURNING: added `nickname, COALESCE(copy_direction,...), COALESCE(execution_mode,...), COALESCE(allow_topups,...)`
  - `update_task` RETURNING: same additions

Created:
- `projects/polymarket/crusaderbot/reports/forge/copy-task-repo-returning-fix.md` (this file)

---

## 4. What is working

- `create_task` now returns a fully-populated `CopyTradeTask` with all migration-035 fields
- `update_task` now returns a fully-populated `CopyTradeTask` with all migration-035 fields
- `_row_to_task` no longer raises `KeyError` for any caller
- 38/38 test_phase5f_copy_wizard.py tests pass; py_compile clean

---

## 5. Known issues

- The `test_phase5f_copy_wizard.py` mock uses a fake DB row that already includes all 4 columns, so the tests were not catching this production bug before the fix. Tests pass because they mock the row — the fix needed was in the SQL RETURNING clause, not the Python access pattern.
- F-HIGH-2 SECONDARY (Phase C signal feed zero candidates): separate operational issue — no active publications in the demo feed for the `subscribed_at > published_at` window. Not a code bug; requires operator to publish new signals to the demo feed.

---

## 6. What is next

- WARP🔹CMD: review + merge this PR
- Fly.io redeploy: copy-task creation will unblock for users on `whale_mirror` preset
- F-HIGH-2 SECONDARY (Phase C): either seed demo feed with current publications, or defer (lib strategies Phase A now generate trades independently)
- Remaining: Lane 4 on-chain withdraw signing skeleton behind EXECUTION_PATH_VALIDATED

Suggested Next Step: WARP🔹CMD review + merge + fly deploy.
