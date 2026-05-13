# WARP•FORGE Report — live-execution-user-id-guards

**Branch:** WARP/live-execution-user-id-guards
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** All position UPDATE statements in `close_position()` bind `user_id` as a parameterized guard so no UPDATE can modify a position owned by a different user.
**Not in Scope:** Enabling live trading, changing `ENABLE_LIVE_TRADING`, real CLOB execution, wallet/key handling, capital/risk sizing, strategy changes, schema migrations.

---

## 1. What was built

Four position UPDATE statements in `domain/execution/live.py` (`close_position`) were missing `AND user_id=$N`. A caller that supplied an arbitrary `position["id"]` could silently UPDATE a row owned by a different user — status flip to `closing`, rollback to `open`, or finalisation to `closed`. All four paths now include a parameterised `user_id` guard:

| Line | Statement | Guard added |
|---|---|---|
| 309–311 | Atomic claim: `SET status='closing'` | `AND user_id=$2` |
| 327–330 | Rollback on CLOB config error: `SET status='open'` | `AND user_id=$2` |
| 341–345 | Rollback on SELL exception: `SET status='open'` | `AND user_id=$2` |
| 360–364 | Finalise close: `SET status='closed'` | `AND user_id=$5` |

The `execute()` (open) path is unaffected: positions are inserted (not updated) and the INSERT already binds `user_id` correctly.

Five new tests in `TestUserIdGuards` validate:
- Claim SQL contains `user_id` and `position["user_id"]` is bound as a parameter.
- Finalize SQL contains `user_id` and `position["user_id"]` is bound as a parameter.
- Rollback on submit failure: executed SQL contains `user_id`.
- Rollback on config error: executed SQL contains `user_id`.
- Cross-user simulation: `close_claim=None` (no row matched) → no SELL submitted, returns `already_closed`.

---

## 2. Current system architecture

```
close_position()
  └── USE_REAL_CLOB guard (pre-claim)
  └── SELECT markets WHERE id=$1           — token lookup (no user_id needed)
  └── UPDATE positions SET status='closing'
        WHERE id=$1 AND user_id=$2 AND status='open'  ← HARDENED
  └── get_clob_client()
        on (ClobConfigError, ClobAuthError):
          UPDATE positions SET status='open'
            WHERE id=$1 AND user_id=$2                ← HARDENED
  └── client.post_order(side='SELL')
        on Exception:
          UPDATE positions SET status='open'
            WHERE id=$1 AND user_id=$2                ← HARDENED
  └── UPDATE positions SET status='closed', ...
        WHERE id=$1 AND user_id=$5 AND status='closing' ← HARDENED
  └── ledger.credit_in_conn()
  └── audit.write()
```

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/domain/execution/live.py` — 4 UPDATE WHERE clauses hardened with `AND user_id=$N`
- `projects/polymarket/crusaderbot/tests/test_live_execution_rewire.py` — `_TrackingConn` helper + `TestUserIdGuards` class (5 tests)

Created:
- `projects/polymarket/crusaderbot/reports/forge/live-execution-user-id-guards.md` — this report

---

## 4. What is working

- All 4 position UPDATE statements in `close_position` bind `user_id` as a parameterised guard; no broad path remains where `position_id` alone determines which row is modified.
- Rollback paths (CLOB config error, SELL exception) are guarded symmetrically with the same `user_id` they claimed under — preventing a rollback from accidentally un-closing a different user's position.
- The finalize UPDATE ($5 parameter) is consistent with the existing $1–$4 binding order.
- Existing paper-only posture unchanged; `execute()` open path unchanged; `ENABLE_LIVE_TRADING` guards unchanged; activation guards remain NOT SET.
- Test class `TestUserIdGuards` covers SQL content, bound-parameter presence, and cross-user negative path.

---

## 5. Known issues

- The test suite cannot be executed in the containerised CI environment due to a `cffi/cryptography` native library conflict unrelated to this change. SQL correctness is validated by direct string inspection (`grep -n "UPDATE positions" domain/execution/live.py`) and by reading the patched file.
- WARP•SENTINEL full runtime validation is required before merge (MAJOR tier).

---

## 6. What is next

WARP•SENTINEL validation required for live-execution-user-id-guards before merge.
Source: `projects/polymarket/crusaderbot/reports/forge/live-execution-user-id-guards.md`
Tier: MAJOR

After SENTINEL APPROVED: WARP🔹CMD merge decision. Once merged, `WARP/live-execution-user-id-guards` can be closed from the NOT STARTED backlog and the live activation prerequisite is satisfied.

---

**Suggested Next Step:** Route to WARP•SENTINEL for MAJOR validation before any merge decision.
