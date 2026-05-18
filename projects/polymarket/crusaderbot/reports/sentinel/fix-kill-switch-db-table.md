# WARP•SENTINEL — fix-kill-switch-db-table

Branch   : WARP/fix-kill-switch-db-table
PR       : #1160
Forge    : projects/polymarket/crusaderbot/reports/forge/fix-warpforge-kill-switch.md
Date     : 2026-05-19 09:03
WARP-17  : kill_switch_exec _set_system_flag system_flags -> system_settings

---

## Environment

| Field | Value |
|---|---|
| Execution surface | Claude Code / CLAUDE.md |
| Active project | CrusaderBot |
| PROJECT_ROOT | projects/polymarket/crusaderbot |
| Environment | dev (validation only — no runtime execution) |
| Tier | MAJOR |
| Claim Level | FULL RUNTIME INTEGRATION |

---

## Validation Context

Validation Target: `_set_system_flag()` + `execute_kill_switch()` + `reset_kill_switch()` write
to `system_settings`; kill switch activation path end-to-end.

Not in Scope: `kill_switch_history` table, `audit_log` write internals, Telegram notify
path, order cancellation path, redundancy removal.

Forge report declares 6 sections. Validation Tier MAJOR. Claim Level FULL RUNTIME INTEGRATION.

---

## Phase 0 Checks

| Check | Result |
|---|---|
| Forge report at correct path + 6 sections | PASS — `reports/forge/fix-warpforge-kill-switch.md` verified |
| Report naming matches branch feature token | PASS — `fix-warpforge-kill-switch` slug, no prefix/date |
| PROJECT_STATE.md updated with full timestamp | PASS — `Last Updated: 2026-05-19 09:02` |
| No `phase*/` folders in PROJECT_ROOT | PASS — no phase*/ directories found (phase-prefixed filenames in reports/ are files, not folders) |
| Hard delete policy | N/A — no files deleted in this PR |
| Implementation evidence for critical layers | PASS — code change visible at `kill_switch_exec.py:26` |
| WARP•FORGE final output has Report:/State:/Validation Tier: | PASS |

Phase 0: **ALL PASS** — validation may proceed.

---

## Findings

### Phase 1 — Functional: `_set_system_flag()` claim

**File:** `projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py`

- **line 26**: `INSERT INTO system_settings (key, value, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()`
  → Correct table. ON CONFLICT (key) valid — `system_settings.key` is UNIQUE per `ops/kill_switch.py:159` identical pattern.
- **line 83**: comment reads "Set system_settings record (kill_switch_active key)" ✓
- **line 87**: `logger.error("kill_switch_exec: system_settings write failed: %s", exc)` ✓
- **line 121**: `logger.error("kill_switch_exec: reset system_settings write failed: %s", exc)` ✓

Claim verified. No residual `system_flags` references in modified file.

### Phase 2 — Path 1: Telegram /kill command

**File:** `projects/polymarket/crusaderbot/bot/handlers/admin.py`

- `admin.py:23-24`: `from ...domain.risk.kill_switch_exec import execute_kill_switch as ks_execute, reset_kill_switch as ks_reset`
- `admin.py:649`: `action == "pause"` → `await ks_execute(reason="Manual admin command", triggered_by=f"admin:{actor_id}")` ✓
- `admin.py:664`: `action == "resume"` → `await ks_reset(triggered_by=...)` ✓
- This file was NOT modified by this PR — no regression possible on the import or call chain.

Path 1: **INTACT** ✓

### Phase 3 — Path 2: Scanner kill switch gate

**File:** `projects/polymarket/crusaderbot/jobs/market_signal_scanner.py`

- `scanner.py:22`: `from ..domain.ops import kill_switch as _ops_kill_switch`
- `scanner.py:369`: `if await _ops_kill_switch.is_active():`
- The scanner reads `system_settings.kill_switch_active` via `ops_kill_switch.is_active()` (SELECT path in `ops/kill_switch.py:96`).
- `_set_system_flag("kill_switch_active", "true")` now correctly writes to the same `system_settings` table the scanner reads. The read/write table is now consistent end-to-end.
- Scanner was NOT modified by this PR.

Path 2: **INTACT** — read/write table alignment confirmed ✓

### Phase 4 — Path 3: Env var startup

**File:** `projects/polymarket/crusaderbot/main.py`

- `main.py:165-166`: `KILL_SWITCH=true` → imports `execute_kill_switch` from `domain.risk.kill_switch_exec` ✓
- Not modified by this PR.

Path 3: **INTACT** ✓

### Phase 5 — Audit log unconditional

**File:** `projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py`

Steps in `execute_kill_switch()` each have independent try/except blocks:
- Step 1 (ops set_active): try/except → logs error if fails, continues
- Step 2 (cancel orders): try/except → logs error if fails, continues
- Step 3 (_set_system_flag): try/except → logs error if fails, continues
- Step 4 (audit_log): try/except → logs error if fails — NOT SKIPPED even if steps 1-3 fail
- Step 5 (notify): try/except → best-effort, non-blocking

Audit log is unconditional — written regardless of prior step failures. ✓

### Phase 6 — No silent failures

- `_set_system_flag()` has no internal try/except — exceptions propagate to caller ✓
- Callers catch and log via `logger.error()` — non-silent ✓
- `_write_audit_log()` similarly propagates exceptions to its caller ✓

### Phase 7 — Risk constants

- Kelly fraction: not touched ✓
- ENABLE_LIVE_TRADING: not bypassed ✓
- No hardcoded secrets: not introduced ✓
- No threading: asyncio-only pattern unchanged ✓

### Phase 8 — Cache invalidation (NEW FINDING — Gemini HIGH)

**File:** `projects/polymarket/crusaderbot/domain/risk/kill_switch_exec.py`

`_set_system_flag()` writes directly to `system_settings` but does NOT call
`ops_kill_switch.invalidate_cache()` after the write.

Scenario: step 1 (`ops_kill_switch.set_active()`) raises an exception (e.g., history
log INSERT fails, causing a transaction rollback). The ops module cache is NOT invalidated
(since `set_active()` calls `invalidate_cache()` at line 265 only on success). Step 3
then runs `_set_system_flag()` and writes `kill_switch_active=true` to `system_settings`
directly — but the cache still holds the old value. `is_active()` returns stale `False`
for up to 30 seconds (CACHE_TTL_SECONDS), allowing new trades to route during that window.

Risk: bounded 30s window, fail-SAFE on DB error (cache miss → returns True). Not critical
in isolation, but materially degrades kill switch responsiveness in the specific
step-1-failure scenario. `invalidate_cache()` is already a public function in the ops module
and is importable from `ops/kill_switch.py`. One-line fix.

**FINDING:** `_set_system_flag()` should call `ops_kill_switch.invalidate_cache()` after the DB write.

---

## Score Breakdown

| Criterion | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20% | 20 | Table reference corrected; consistent with ops module canonical pattern |
| Functional | 20% | 20 | All 3 activation paths verified intact; claim confirmed at line 26 |
| Failure modes | 20% | 15 | Non-silent, audit unconditional; cache not invalidated after step 3 write (Phase 8 finding) |
| Risk | 20% | 20 | No risk constants touched; live guard intact |
| Infra + TG | 10% | 8 | Code logic verified correct; no live runtime execution in this environment |
| Latency | 10% | 10 | Single SQL upsert — no latency concern introduced |
| **Total** | | **93/100** | |

---

## Critical Issues

None found. Phase 8 finding is a bounded safety gap (30s, fail-safe), not a hard blocker.

---

## Status

**APPROVED** — Score: 93/100. Zero critical issues.

All activation paths verified intact. Table reference fix confirmed correct and consistent
with the canonical `system_settings` table used throughout `domain/ops/kill_switch.py`.
Audit log write is unconditional. No risk constants changed. No silent failures.
One non-critical finding (Phase 8): cache invalidation missing after step 3 write —
bounded 30s window in step-1-failure scenario. Fix recommended before or immediately after merge.

---

## PR Gate Result

| Gate | Result |
|---|---|
| GATE 1 — Branch format | PASS — `WARP/fix-kill-switch-db-table` ✓ |
| GATE 2 — PR body declarations | PASS — all 4 fields present |
| GATE 3 — Forge report | PASS — correct path, 6 sections, valid naming |
| GATE 4 — PROJECT_STATE.md | PASS — updated, full timestamp, scope-bound edit |
| GATE 5 — Hard stops | PASS — no secrets, no full Kelly, no threading, no ENABLE_LIVE_TRADING bypass |
| GATE 6 — Drift checks | PASS — imports resolve, report claims match code |
| GATE 7 — PR type / merge order | PASS — SENTINEL PR does not precede WARP•FORGE PR |
| GATE 8 — MAJOR flag | INFO — MAJOR tier; WARP•SENTINEL audit satisfied |

---

## Broader Audit Finding

No broader issues found outside the declared fix scope.

The pre-existing double-write pattern (step 1 via `ops_kill_switch.set_active()` + step 3 via
`_set_system_flag()` both writing `kill_switch_active` to `system_settings`) is a defense-in-depth
design decision that predates this PR. It is not a regression and is not blocking. See Deferred
Minor Backlog below.

---

## Reasoning

The change is minimal and surgical — two SQL token changes (table name) and two log string
updates. The fix closes a latent bug where step 3 of `execute_kill_switch()` was silently
failing on every activation (PostgreSQL would have raised UndefinedTableError on `system_flags`).
Step 1 (`ops_kill_switch.set_active()`) was already correctly writing to `system_settings`, so
kill switch activation was not broken — but the error was being swallowed and logged at step 3
on every activation event. This fix eliminates that logged error and ensures step 3 succeeds.

---

## Fix Recommendations

**P1 — Cache invalidation after `_set_system_flag()` write**

In `kill_switch_exec.py`, add `ops_kill_switch.invalidate_cache()` after the DB execute call
inside `_set_system_flag()`. The `ops_kill_switch` module is already imported at file scope.

```python
async def _set_system_flag(key: str, value: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO system_settings (key, value, updated_at) VALUES ($1, $2, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=NOW()",
            key, value,
        )
    ops_kill_switch.invalidate_cache()
```

This ensures the in-process cache is cleared immediately after any direct write to
`system_settings`, regardless of whether step 1 (`set_active()`) succeeded.
WARP🔹CMD may merge as-is or direct WARP•FORGE to apply this fix first.

---

## Out-of-scope Advisory

- **Step 3 double-write**: `execute_kill_switch()` step 3 writes `kill_switch_active=true` to
  `system_settings`, duplicating step 1's write. Existing architectural pattern. Removal would
  require confirming no caller depends on step 3 as a fallback path. Out of scope for this fix.
  Recommend WARP🔹CMD evaluates in a dedicated cleanup lane if desired.

---

## Deferred Minor Backlog

- [DEFERRED] Step 3 double-write to `system_settings` (`_set_system_flag` + `ops_kill_switch.set_active`).
  Defense-in-depth pattern; pre-existing. Not introduced by this PR. Separate cleanup lane if required.

---

## Telegram Visual Preview

N/A — no new Telegram-facing behavior introduced by this PR. Kill switch Telegram notification
template (existing `notify_operator` call in step 5) is unchanged and not in validation scope.

---

Done -- GO-LIVE: APPROVED. Score: 93/100. Critical: 0.
PR: WARP/fix-kill-switch-db-table (#1160)
Report: projects/polymarket/crusaderbot/reports/sentinel/fix-kill-switch-db-table.md
State: PROJECT_STATE.md updated
NEXT GATE: Return to WARP🔹CMD for final decision. P1 fix recommended: cache invalidation in _set_system_flag().
