# WARP•SENTINEL Report — live-execution-user-id-guards

**Branch:** WARP/live-execution-user-id-guards
**Source Forge Report:** projects/polymarket/crusaderbot/reports/forge/live-execution-user-id-guards.md
**Validation Tier:** MAJOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** live execution persistence updates positions only when both position_id and user_id match
**Not in Scope:** enabling live trading, ENABLE_LIVE_TRADING changes, real CLOB activation, wallet/key handling, capital/risk sizing, strategy behavior, schema migration
**Environment:** N/A — validation halted at precondition
**Date:** 2026-05-13 10:30 Asia/Jakarta

---

## TEST PLAN

Planned phases: Phase 0 pre-test → Phase 1 functional → Phase 2 pipeline → Phase 3 failure modes → Phase 4 async safety → Phase 5 risk rules → Phase 6 latency → Phase 7 infra → Phase 8 Telegram.

**Status: HALTED at precondition check.**

Reason: PR #1021 `mergeable_state` = `"dirty"`. Per task precondition, validation must not start until the dirty merge state is resolved and CI is green. CI is green; merge conflict is not.

---

## FINDINGS

### Precondition Check

| Check | Result |
|---|---|
| PR head branch = `WARP/live-execution-user-id-guards` | PASS |
| PR `mergeable_state` | FAIL — `dirty` (merge conflict with main) |
| CI: Lint + Test | PASS — `success` |
| CI: WARP Auto Gate | PASS — `success` |

**Precondition verdict: BLOCKED.** Merge conflict with main must be resolved before WARP•SENTINEL validation can proceed.

### Preliminary Code Observation (non-binding — Phase 0 not reached)

Observed from PR diff only. Not a formal validation finding. Reported to assist FORGE when rebasing.

**live.py — claim UPDATE (line ~309):**
```sql
UPDATE positions SET status='closing'
WHERE id=$1 AND user_id=$2 AND status='open' RETURNING id
```
Parameters: `position["id"], position["user_id"]` — parameterized. ✓

**live.py — CLOB config error rollback (line ~327):**
```sql
UPDATE positions SET status='open' WHERE id=$1 AND user_id=$2
```
Parameters: `position["id"], position["user_id"]` — parameterized. ✓

**live.py — SELL exception rollback (line ~341):**
```sql
UPDATE positions SET status='open' WHERE id=$1 AND user_id=$2
```
Parameters: `position["id"], position["user_id"]` — parameterized. ✓

**live.py — final close UPDATE (line ~360):**
```sql
UPDATE positions SET status='closed', exit_reason=$2,
current_price=$3, pnl_usdc=$4, closed_at=NOW()
WHERE id=$1 AND user_id=$5 AND status='closing' RETURNING id
```
Parameters: `position["id"], exit_reason, exit_price, pnl, position["user_id"]` — $5 position correct. ✓

**py_compile:** `python -m py_compile` on PR head SHA `a296914b` — **COMPILE_OK**

**Artifact traceability:**
- Forge report branch line: `WARP/live-execution-user-id-guards` ✓
- CHANGELOG.md entry branch: `WARP/live-execution-user-id-guards` ✓
- PROJECT_STATE.md (PR head): references correct branch ✓
- No stale `warp/forge-task-for-issue-1012` references observed in changed files ✓

**Tests (TestUserIdGuards — observed from diff, not executed):**
- 5 tests present: claim SQL, finalize SQL, rollback-submit, rollback-config, cross-user claim=None
- Cross-user test uses `close_claim=None` → asserts `exit_reason == "already_closed"` and zero open orders ✓
- `_TrackingConn` helper records fetchval calls for SQL/param inspection ✓

**Safety posture (observed from PR diff):**
- No changes to `ENABLE_LIVE_TRADING` or `USE_REAL_CLOB` guards observed ✓
- No schema migration added ✓
- No wallet/key/capital/risk/strategy code touched ✓

*These observations are informational only. Formal validation requires rebase and clean merge state.*

---

## CRITICAL ISSUES

| # | Severity | Finding | Location |
|---|---|---|---|
| 1 | CRITICAL | PR `mergeable_state` = `dirty` — merge conflict with main blocks validation | PR #1021 |

---

## STABILITY SCORE

Score: **0 / 100**

Reason: Validation halted at precondition. No phases executed. Any critical issue = 0 + BLOCKED per WARP•SENTINEL rules.

---

## GO-LIVE STATUS

**BLOCKED**

Reason: `mergeable_state` = `dirty`. Merge conflict with `main` must be resolved by WARP•FORGE before WARP•SENTINEL can begin Phase 0. Preliminary code observation is encouraging (py_compile clean, parameterization appears correct) but does not constitute validation.

---

## FIX RECOMMENDATIONS

1. **CRITICAL — P0:** WARP•FORGE must rebase `WARP/live-execution-user-id-guards` onto current `main` and resolve all merge conflicts. Push the rebased branch to update PR #1021.
2. After rebase, confirm CI re-runs and all checks pass.
3. Once `mergeable_state` is no longer `dirty` and CI is green, re-route to WARP•SENTINEL for full MAJOR validation.

---

## TELEGRAM PREVIEW

N/A — validation did not complete. No alert or dashboard data generated.

---

**Suggested Next Step:** WARP•FORGE rebase `WARP/live-execution-user-id-guards` onto `main`, push, confirm CI green, then re-trigger WARP•SENTINEL validation.
