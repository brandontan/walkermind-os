# WARP•FORGE — fix-warpforge-kill-switch

## 1. What was built

Fixed `_set_system_flag()` in `domain/risk/kill_switch_exec.py` to reference the correct
database table `system_settings` instead of the non-existent `system_flags` table.
The `INSERT ... ON CONFLICT (key)` query is now aligned with the canonical table used
throughout `domain/ops/kill_switch.py`. Inline comment updated for accuracy.

## 2. Current system architecture (relevant slice)

Kill switch activation converges on three paths, all calling `execute_kill_switch()`:

```
Path 1  Telegram /kill command   → bot/handlers/admin.py        → execute_kill_switch()
Path 2  DB flag checked per tick → jobs/market_signal_scanner.py → execute_kill_switch()
Path 3  Env KILL_SWITCH=true     → main.py startup              → execute_kill_switch()
```

Inside `execute_kill_switch()` (kill_switch_exec.py):
1. `ops_kill_switch.set_active(action="pause")` — writes kill_switch_active to `system_settings` (canonical, via ops module)
2. Cancel pending orders — `orders` table
3. **[FIXED]** `_set_system_flag("kill_switch_active", "true")` — now targets `system_settings`
4. Audit row — `audit_log` table
5. Telegram admin notify — best-effort, non-blocking

`domain/ops/kill_switch.py` is the canonical writer for `system_settings`. Step 3 now
correctly mirrors that table rather than targeting a non-existent `system_flags` table.

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py`
  - line 27: `system_flags` → `system_settings` in INSERT query
  - line 83: comment updated — "system_flags record (Track D flag table)" → "system_settings record (kill_switch_active key)"

## 4. What is working

- `_set_system_flag()` now targets `system_settings` — the table that actually exists and
  holds kill switch state
- `ON CONFLICT (key)` clause is valid — `system_settings.key` has a UNIQUE constraint,
  confirmed by identical upsert pattern in `domain/ops/kill_switch.py:159`
- Value type consistency: both ops module and `_set_system_flag()` write string "true"/"false"
  to the `value TEXT` column — no type mismatch
- No silent failure: `_set_system_flag()` propagates exceptions; callers in
  `execute_kill_switch()` and `reset_kill_switch()` catch and log via `logger.error()` —
  non-silent by design
- `py_compile` passes on modified file

## 5. Known issues

- Branch `claude/fix-warpforge-kill-switch-4A9Gy` does not conform to `WARP/{feature}`
  naming rule (GATE 1 P0 in automated review). Branch was harness-assigned for this session.
  WARP🔹CMD should rename or re-target to a compliant branch before merge.

## 6. What is next

```
Validation Tier   : MAJOR
Claim Level       : FULL RUNTIME INTEGRATION
Validation Target : _set_system_flag() + execute_kill_switch() + reset_kill_switch()
                    write to system_settings; kill switch activation path end-to-end
Not in Scope      : kill_switch_history table, audit_log writes, Telegram notify path,
                    order cancellation path, ops/kill_switch.py (unchanged)
Suggested Next    : WARP•SENTINEL validation required before merge (MAJOR tier)
```
