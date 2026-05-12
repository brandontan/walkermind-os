# WARP•SENTINEL — Validation Report

PR #1003 | `WARP/fix-migration-idempotency`
Tier: MAJOR | Claim: NARROW INTEGRATION
Date: 2026-05-12 23:45 Asia/Jakarta

---

## Phase 0 — Pre-Test

Source material confirmed:

- Forge report: `projects/polymarket/crusaderbot/reports/forge/fix-migration-idempotency.md` — read ✅
- Diff: 3 runtime files + 3 state/report files — read ✅
- Sentry ground truth: DAWN-SNOWFLAKE-1729-2 & -3, 122 events, `UniqueViolationError` on startup — verified ✅
- WARP🔹CMD review: HOLD pending SENTINEL ✅

---

## Phase 1 — Claim Validation

Claim: NARROW INTEGRATION — fix scoped to `run_migrations()` startup path + `signal_feeds` seed INSERTs in migrations 024 and 025.

| Claim element | Reality in diff | Match |
|---|---|---|
| `run_migrations()` modified | Yes — `database.py` lines 116–129 | ✅ |
| Migration 024 seed INSERT modified | Yes — 1 line change | ✅ |
| Migration 025 seed INSERT modified | Yes — 1 line change | ✅ |
| Schema changes | None | ✅ |
| Execution/risk path | Not touched | ✅ |
| Other migration SQL content | Not touched | ✅ |

Claim matches diff. No overclaim.

---

## Phase 2 — Code Truth

### 2.1 — SQL Fix: `ON CONFLICT DO NOTHING`

**024_signal_scan_engine_seed.sql & 025_heisenberg_live_feed.sql:**

```sql
-- Before
ON CONFLICT (id) DO NOTHING

-- After
ON CONFLICT DO NOTHING
```

Verdict: Correct. PostgreSQL semantics confirmed:

- `ON CONFLICT (id) DO NOTHING` — only guards PRIMARY KEY conflicts. Slug UNIQUE constraint on a separate column is not caught.
- `ON CONFLICT DO NOTHING` (without target) — suppresses all unique constraint violations on the INSERT statement, including `slug VARCHAR(60) UNIQUE`.

This is the correct root cause fix for `UniqueViolationError: duplicate key value violates unique constraint "signal_feeds_slug_key"`.

Scope check: Only seed INSERT for `signal_feeds` changed per file. All other migration INSERT statements audited and confirmed already idempotent. ✅

### 2.2 — `run_migrations()` Error Handling

```python
try:                                          # outer
    async with pool.acquire() as conn:
        for f in files:
            sql = f.read_text(encoding="utf-8")
            logger.info("Running migration %s", f.name)
            try:                              # inner (per-file)
                await conn.execute(sql)
            except Exception as exc:
                logger.error(
                    "Migration failed: %s — %s", f.name, exc, exc_info=True
                )
                raise                         # re-raise to outer
except Exception as exc:
    logger.error("run_migrations failed: %s", exc, exc_info=True)
    raise                                     # re-raise to lifespan
logger.info("Migrations complete (%d files)", len(files))
```

**Checks:**

- **Silent failure:** None. Both `raise` preserved. Exception propagates to lifespan → startup abort. ✅
- **Connection lifecycle:** `async with pool.acquire() as conn:` as context manager. On exception, context manager exits cleanly; connection returned/discarded by asyncpg pool. No dangling connection. ✅
- **Transaction safety:** Migration 025 contains explicit `BEGIN`/`COMMIT`. `conn.execute(sql)` sends full file as one string to PostgreSQL — explicit transaction block handled server-side. No implicit asyncpg transaction wrapper. Safe. ✅
- **Exception scope:** `except Exception` broad — acceptable for migration runner startup context. No `except: pass` or swallow. ✅

### 2.3 — Asyncpg Transaction State Risk

With fix applied, migration 024 will not crash — `ON CONFLICT DO NOTHING` turns conflict into no-op. For general resilience: `pool.acquire()` context manager properly returns/discards connection on exception propagation. asyncpg does not leak connections when context manager cleanup runs in `__aexit__`. ✅

### 2.4 — Idempotency Verification

| Scenario | Behavior |
|---|---|
| Fresh DB | INSERT succeeds, slug created |
| Restart — slug exists, same UUID | `ON CONFLICT DO NOTHING` → no-op ✅ |
| Restart — slug exists, different UUID | `ON CONFLICT DO NOTHING` → no-op ✅ (was crashing) |
| Hard migration error (non-conflict) | Log + re-raise + startup abort ✅ |

---

## Phase 3 — Safety Gates

| Gate | Finding |
|---|---|
| Hardcoded secrets | None ✅ |
| Full Kelly fraction | Not present — fractional Kelly (0.25) enforced ✅ |
| Bare exception swallowing | Not present — all exceptions log and re-raise ✅ |
| `import threading` | Not present ✅ |
| `phase*/` folder | Not created ✅ |
| `ENABLE_LIVE_TRADING` guard bypass | Not touched ✅ |
| Capital / risk / execution path | Not touched ✅ |
| Paper mode posture | Unchanged ✅ |

---

## Phase 4 — State File Audit

**PROJECT_STATE.md:**

- `Last Updated` format correct ✅
- ASCII brackets confirmed ✅
- `[IN PROGRESS]` entries scope-bound to this PR ✅
- Existing items outside scope preserved ✅

**CHANGELOG.md:**

- Format correct (`timestamp | branch | summary`) ✅
- Append-only ✅
- Required action post-merge: Remove "PR open awaiting WARP•SENTINEL", update timestamp to actual merge time.

**Forge report:** 6 sections present, content matches diff reality, no overclaim. ✅

---

## Phase 5 — Findings Summary

| # | Severity | Finding |
|---|---|---|
| F-01 | INFO | Double-logging on failure (inner + outer except). Noisy, not harmful. |
| F-02 | INFO | CHANGELOG entry pre-written before lane close. Needs amend post-merge. |
| F-03 | INFO | `ON CONFLICT DO NOTHING` (broader) vs `ON CONFLICT (slug) DO NOTHING` (precise). Acceptable for seed context. |

Zero blocking findings.

---

## SENTINEL Verdict

```
══════════════════════════════════════════════
WARP•SENTINEL VERDICT: APPROVED
PR #1003 — WARP/fix-migration-idempotency
Score: 95/100 | Critical: 0
══════════════════════════════════════════════

Fix is technically correct.
Root cause accurately identified and addressed.
Claim matches implementation.
No safety violations.
No silent failures.
No hard stops.

APPROVED FOR MERGE by WARP🔹CMD.

Post-merge required:
  1. Amend CHANGELOG entry — remove "PR open awaiting WARP•SENTINEL",
     update timestamp to actual merge time.
  2. Monitor Sentry: DAWN-SNOWFLAKE-1729-2 and -3 must stop firing
     after deployment.
══════════════════════════════════════════════
```
