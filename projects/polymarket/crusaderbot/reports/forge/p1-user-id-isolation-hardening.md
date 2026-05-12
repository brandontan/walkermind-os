# WARP•FORGE Report — p1-user-id-isolation-hardening

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: 5 UPDATE statements in domain/positions/registry.py and domain/execution/paper.py
Not in Scope: ENABLE_LIVE_TRADING, execution logic, live.py close path, lifecycle.py, SENTINEL audit
Suggested Next Step: WARP🔹CMD review — merge when satisfied

---

## 1. What Was Built

Added `AND user_id = $N` guards to all 5 UPDATE statements identified as missing per-user scope.
Also updated the 3 call sites in `domain/execution/exit_watcher.py` that invoke the changed registry functions.
No logic was changed — WHERE clause additions and matching parameter bindings only.

---

## 2. Current System Architecture

No architectural change. The positions table already carries a `user_id` column (established in Track J
Multi-User Isolation Audit, MERGED PR #988). This task wires the missing WHERE conditions so UPDATE
statements cannot affect rows owned by a different user even if a position_id UUID were somehow reused
or leaked across users.

Pipeline: DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING — unchanged.
Execution guard: ENABLE_LIVE_TRADING remains OFF. Paper-only posture unchanged.

---

## 3. Files Created / Modified

Modified:
- `projects/polymarket/crusaderbot/domain/positions/registry.py` — 4 functions updated
- `projects/polymarket/crusaderbot/domain/execution/paper.py` — 1 UPDATE updated
- `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` — 3 call sites updated

No files created. No files deleted.

---

## 4. What Is Working

### Fix 1 — registry.py `update_current_price` (line 200)

Before:
```sql
UPDATE positions SET current_price = $1 WHERE id = $2
-- args: (price, position_id)
```
After:
```sql
UPDATE positions SET current_price = $1 WHERE id = $2 AND user_id = $3
-- args: (price, position_id, user_id)
```
Function signature: `async def update_current_price(position_id: UUID, price: float, user_id: UUID) -> None`
Call site (exit_watcher.py:177): `await registry.update_current_price(position.id, decision.current_price, position.user_id)`

---

### Fix 2 — registry.py `record_close_failure` (line 215)

Before:
```sql
UPDATE positions SET close_failure_count = close_failure_count + 1 WHERE id = $1 RETURNING close_failure_count
-- args: (position_id,)
```
After:
```sql
UPDATE positions SET close_failure_count = close_failure_count + 1 WHERE id = $1 AND user_id = $2 RETURNING close_failure_count
-- args: (position_id, user_id)
```
Function signature: `async def record_close_failure(position_id: UUID, user_id: UUID) -> int`
Call site (exit_watcher.py:190): `await registry.record_close_failure(position.id, position.user_id)`

---

### Fix 3 — registry.py `reset_close_failure` (line 229)

Before:
```sql
UPDATE positions SET close_failure_count = 0 WHERE id = $1
-- args: (position_id,)
```
After:
```sql
UPDATE positions SET close_failure_count = 0 WHERE id = $1 AND user_id = $2
-- args: (position_id, user_id)
```
Function signature: `async def reset_close_failure(position_id: UUID, user_id: UUID) -> None`
Call site (exit_watcher.py:219): `await registry.reset_close_failure(position.id, position.user_id)`

---

### Fix 4 — registry.py `finalize_close_failed` (line 250)

Before:
```sql
UPDATE positions SET status = 'close_failed', exit_reason = $2, closed_at = NOW()
 WHERE id = $1 AND status = 'open'
 RETURNING id
-- args: (position_id, ExitReason.CLOSE_FAILED.value)
```
After:
```sql
UPDATE positions SET status = 'close_failed', exit_reason = $2, closed_at = NOW()
 WHERE id = $1 AND status = 'open' AND user_id = $3
 RETURNING id
-- args: (position_id, ExitReason.CLOSE_FAILED.value, user_id)
```
Function signature: `async def finalize_close_failed(position_id: UUID, user_id: UUID, error_msg: str) -> bool`
No active call sites — function is exported but not yet invoked in any path. Guard is pre-wired for when it is called.

---

### Fix 5 — paper.py `close_position` (line 114)

Before:
```sql
UPDATE positions SET status='closed', exit_reason=$2, current_price=$3, pnl_usdc=$4, closed_at=NOW()
 WHERE id=$1 AND status='open'
 RETURNING id
-- args: (position["id"], exit_reason, exit_price, pnl)
```
After:
```sql
UPDATE positions SET status='closed', exit_reason=$2, current_price=$3, pnl_usdc=$4, closed_at=NOW()
 WHERE id=$1 AND status='open' AND user_id=$5
 RETURNING id
-- args: (position["id"], exit_reason, exit_price, pnl, position["user_id"])
```
`position["user_id"]` was already present in scope (used by ledger.credit_in_conn and audit.write on lines 124-129). No additional parameter plumbing needed.

---

## 5. Known Issues

None introduced by this change.

---

## 6. Additional Scan — Other UPDATE/DELETE in domain/ Missing user_id

Scanned all `*.py` in `domain/` for UPDATE and DELETE statements not containing `user_id`.
Findings below are **not fixed in this task** — reported for WARP🔹CMD awareness.

### domain/execution/live.py — live close path (lines 309, 328, 343, 361–363)

Four position UPDATEs in the live CLOB close flow do not include `user_id`:

- Line 309: `UPDATE positions SET status='closing' WHERE id=$1 AND status='open'` — claim lock
- Line 328: `UPDATE positions SET status='open' WHERE id=$1` — rollback on CLOB config error
- Line 343: `UPDATE positions SET status='open' WHERE id=$1` — rollback on post_order exception
- Line 361–363: `UPDATE positions SET status='closed'... WHERE id=$1 AND status='closing'` — final close

Severity: MEDIUM. `live.py` is behind ENABLE_LIVE_TRADING=false; no live capital at risk in current paper posture. However, this is the most critical path for when the guard flips. Recommend addressing in a dedicated lane before live activation.

### domain/execution/live.py — orders UPDATEs (lines 172, 183, 220)

Three order UPDATEs use only order UUID (no user_id). Order UUIDs are not guessable and are already user-scoped through FK, but explicit user_id guards would provide defence-in-depth.

### domain/execution/lifecycle.py — orders and positions UPDATEs (lines 252, 282, 382, 418, 436, 491, 525, 719)

Multiple UPDATE statements scoped by order_id or position_id only. The `positions` UPDATE at line 282 uses `WHERE order_id = $1 AND status = 'open'` which is indirectly user-scoped through the order FK — lower isolation risk but still worth auditing for the live path.

### domain/signal/copy_trade.py (line 75)

`UPDATE copy_targets SET last_seen_tx=$1 WHERE id=$2` — `copy_targets` table likely has its own user scope. Low priority.

### domain/copy_trade/repository.py (lines 112, 148)

`UPDATE copy_trade_tasks` — scoped by task UUID. Isolated table. Low priority.

### domain/ops/kill_switch.py and domain/execution/fallback.py

`UPDATE users SET auto_trade_on=FALSE` and `UPDATE user_settings SET trading_mode='paper'` — intentional system-wide operator actions. Not a user isolation issue.

---

## 7. What Is Next

- WARP🔹CMD review and merge decision for this PR (STANDARD tier)
- Recommended follow-up lane: `WARP/live-execution-user-id-guards` to add `AND user_id=$N` to the 4 positions UPDATEs in `domain/execution/live.py` before ENABLE_LIVE_TRADING activation
