# WARP•FORGE Report — R12f Operator Dashboard + Kill Switch

Lane: `WARP/CRUSADERBOT-R12F-OPERATOR-DASHBOARD`
Date: 2026-05-05 (Asia/Jakarta)
Validation Tier: STANDARD
Claim Level: OPERATOR TOOLING ONLY — no new execution path; kill switch
integrates at risk gate step [1] only.
Validation Target: operator-only Telegram surface (`/ops_dashboard`,
`/killswitch`, `/jobs`, `/auditlog`), kill-switch state machine,
job-runs observability.
Not in Scope: trading logic, risk constants, execution path, user-facing
handlers, multi-operator support, email-verify unlock, on-chain sweep.
Suggested Next Step: WARP🔹CMD review and merge — STANDARD tier; no
SENTINEL audit required per task brief.

---

## 1. What was built

### `/ops_dashboard`
Operator-only system snapshot in Telegram. One reply with:

- App uptime + Fly.io machine id (or hostname fallback)
- DB ping result
- Active users (Tier 2+) count
- Open positions count (all users)
- Total USDC balance across all sub-account wallets
- Auto-trade enabled users count
- Kill switch state (ACTIVE / inactive, plus LOCK marker if lock-mode)
- Last 3 job runs with status icon and duration

Refresh + Pause/Resume + Lock buttons attached to the reply via the new
`ops:` callback prefix. Each field degrades to `N/A` (or an error footer)
if the underlying read fails — the snapshot never crashes the operator
flow.

### `/killswitch <pause|resume|lock>`
Single-operator command that flips the kill switch through one
authoritative path:

- `pause`  — sets `system_settings.kill_switch_active=true`. Risk gate
  step [1] starts rejecting new trades within ≤30s (the cache TTL).
  All Tier 2+ users get a Telegram broadcast.
- `resume` — sets `kill_switch_active=false` and clears
  `kill_switch_lock_mode`. Operator gets a confirmation reply.
- `lock`   — sets both flags true AND flips every `users.auto_trade_on`
  to FALSE in a single SQL statement. Reports the count of affected
  users. Operator must run `/killswitch resume` separately to unlock;
  users must re-opt-in.

Every flip writes one row to `kill_switch_history` AND one row to
`audit.log` (action `kill_switch_pause` / `_resume` / `_lock`).

### `/jobs [n] [failed]`
Tail of `job_runs`, default 10, max 50 (`MAX_OPS_LIMIT`). `failed`
filters to status='failed'. Errors are truncated to 80 chars in the
output.

### `/auditlog [n]`
Read-only tail of `audit.log`, default 20, max 50. Renders ts /
actor_role / action / truncated user_id. No write or delete code path
exists in the new module — only `SELECT`.

### Kill-switch domain module (`domain/ops/kill_switch.py`)
Single source of truth for the operator pause flag.
- `is_active(conn=None)` — cached read with 30s TTL. Cold-cache
  contention is coalesced through one `asyncio.Lock`. Fails SAFE: a
  DB read error returns `True` so the gate stays closed.
- `set_active(action, actor_id, reason)` — transactional upsert into
  `system_settings` + history append + cache invalidation. Lock action
  also flips `users.auto_trade_on=FALSE`.
- `record_history(...)`, `fetch_history(limit)`, `get_lock_mode(...)`,
  `invalidate_cache()` — supporting helpers.

### Job-runs tracker (`domain/ops/job_tracker.py` + scheduler listener)
APScheduler `EVENT_JOB_SUBMITTED | EXECUTED | ERROR` listener writes
one `job_runs` row per scheduled job execution. Captures wallclock
start in the SUBMITTED handler so duration is accurate even when a
misfire shifts `scheduled_run_time`. DB write failures are logged but
never block scheduler progress.

### Risk gate integration (single line)
`domain/risk/gate.py` step [1] now imports
`domain.ops.kill_switch.is_active` instead of the old uncached
`database.is_kill_switch_active`. The legacy database helper is now a
compatibility wrapper that delegates to the new module so the legacy
inline-keyboard callback (`bot/handlers/admin.py:admin_callback`) and
the REST API (`api/admin.py`) stay on the same source of truth.

### Migration `007_ops.sql`
Three new tables — `system_settings`, `kill_switch_history`, `job_runs`
— all `IF NOT EXISTS`. Seed rows for `kill_switch_active=false` and
`kill_switch_lock_mode=false` written via `ON CONFLICT DO NOTHING` so a
re-run on a paused production DB never silently flips the switch back
to inactive. Indexes on `kill_switch_history(ts DESC)` and
`job_runs(started_at DESC)` + `(status, started_at DESC)` keep tail
reads cheap.

---

## 2. Current system architecture

```
Telegram operator
    │
    ▼
bot/handlers/admin.py
  /ops_dashboard ── _collect_dashboard_snapshot() ──► DB + job_tracker.fetch_recent
  /killswitch    ── _apply_killswitch_action()    ──► domain.ops.kill_switch.set_active
                                                       └─► system_settings (upsert)
                                                       └─► kill_switch_history (insert)
                                                       └─► users.auto_trade_on (lock only)
                                                       └─► audit.log (audit.write)
                                                       └─► broadcast to users (notifications.send)
  /jobs          ── job_tracker.fetch_recent()    ──► job_runs SELECT
  /auditlog      ── _fetch_audit_tail()           ──► audit.log SELECT (read-only)

scheduler.py
  setup_scheduler()
    └── add_listener(_job_tracker_listener,
                     EVENT_JOB_SUBMITTED | EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)
              └─► job_tracker.mark_job_submitted / record_job_event ── job_runs INSERT

domain/risk/gate.py step [1]
    └── domain.ops.kill_switch.is_active()  (30s TTL cache)
              └─► system_settings SELECT (cold cache only)

database.py
  is_kill_switch_active() / set_kill_switch()
    └── thin wrappers delegating to domain.ops.kill_switch  (single source of truth)
```

---

## 3. Files created / modified (full repo-root paths)

### Created
- `projects/polymarket/crusaderbot/migrations/007_ops.sql`
- `projects/polymarket/crusaderbot/domain/ops/__init__.py`
- `projects/polymarket/crusaderbot/domain/ops/kill_switch.py`
- `projects/polymarket/crusaderbot/domain/ops/job_tracker.py`
- `projects/polymarket/crusaderbot/bot/keyboards/admin.py`
- `projects/polymarket/crusaderbot/tests/test_kill_switch.py`
- `projects/polymarket/crusaderbot/tests/test_admin_handlers.py`
- `projects/polymarket/crusaderbot/reports/forge/r12f-operator-dashboard.md`

### Modified
- `projects/polymarket/crusaderbot/bot/handlers/admin.py` — added
  `_format_uptime`, `_format_duration_ms`, `_truncate`, `_parse_limit`,
  `_collect_dashboard_snapshot`, `_render_dashboard`, `_render_jobs`,
  `_render_auditlog`, `_apply_killswitch_action`, `_broadcast_pause`,
  `_fetch_audit_tail`, `ops_dashboard_command`, `ops_dashboard_callback`,
  `killswitch_command`, `jobs_command`, `auditlog_command`. Promoted
  `notifications` import to module scope.
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registered
  `/ops_dashboard`, `/killswitch`, `/jobs`, `/auditlog` command handlers
  and the `^ops:` callback handler.
- `projects/polymarket/crusaderbot/database.py` — converted
  `is_kill_switch_active()` and `set_kill_switch()` to thin wrappers
  around the new domain module (single source of truth).
- `projects/polymarket/crusaderbot/domain/risk/gate.py` — step [1] now
  calls `domain.ops.kill_switch.is_active` (cached 30s).
- `projects/polymarket/crusaderbot/scheduler.py` — registered the
  APScheduler listener on `setup_scheduler()`. No trading logic changed.
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`,
  `state/WORKTODO.md`, `state/CHANGELOG.md` — surgical state sync.

### Note on path naming
Task brief specified `infra/migrations/007_ops.sql`. The repo's existing
convention is `projects/polymarket/crusaderbot/migrations/` (where
001–006 already live and where `database.run_migrations()` reads from).
The migration was placed there to remain idempotent with the existing
`run_migrations` glob.

---

## 4. What is working

- All 51 new tests pass; full CrusaderBot suite 140 / 140 green.
  Coverage:
  - `is_active`: cold-cache, warm-cache, fail-safe-on-error, conn pass-through
  - `set_active`: pause / resume / lock paths, history row, cache invalidation
  - `record_history` validation, `fetch_history` limit handling
  - All four R12f commands silently reject non-operators
  - Operator gate happy paths: dashboard renders, killswitch usage / pause /
    resume / lock replies, /jobs default + failed filter, /auditlog default
  - All pure formatters: uptime, duration (ms / s / m), truncate, parse_limit
  - Dashboard renderer: kill-switch active vs. inactive, lock marker,
    missing-field N/A path, error footer
- Kill switch read on the hot path is non-blocking: warm cache returns
  immediately; cold cache coalesces under a single asyncio lock so a
  burst of signals does not produce parallel SELECTs.
- `database.is_kill_switch_active()` and `set_kill_switch()` keep their
  signatures; the legacy admin inline-keyboard callback and `api/admin.py`
  REST endpoint continue to work without code changes on their side and
  share the new source of truth.
- Migration is idempotent: re-running on a DB whose
  `kill_switch_active=true` does not silently revert it (ON CONFLICT
  DO NOTHING on seed inserts; CREATE TABLE IF NOT EXISTS for tables;
  CREATE INDEX IF NOT EXISTS).

---

## 5. Known issues

- Up to 30 seconds of propagation between `/killswitch pause` and the
  risk gate seeing it on a *different* process. On the same process the
  set_active call invalidates the cache immediately, so the operator's
  acknowledgement is consistent with the local gate. Multi-instance
  deployments will see ≤30s skew between machines — accepted per the
  task brief.
- `/killswitch lock` does not yet require email verification to unlock;
  unlock is operator-manual via `/killswitch resume`. Email-verify path
  was explicitly deferred in the task brief.
- The legacy `kill_switch` table (created in `001_init.sql`) is no
  longer authoritative but is left in place to avoid a cross-cutting
  drop migration. No code path reads from it after this lane.
- `_broadcast_pause` fans out per-user `notifications.send` calls
  serially. For >1k users a Tier-2+ pause broadcast will take a few
  seconds; acceptable for an operator-triggered event.
- F401 warnings on the file's pre-existing imports remain unchanged
  from the deferred cleanup lane noted in WORKTODO.

---

## 6. What is next

- WARP🔹CMD review of this PR (STANDARD tier — no SENTINEL required).
- Open lanes that R12f does NOT block:
  - R12c exit-watcher merge (PR #865) — independent.
  - R12a CI/CD pipeline merge — independent.
  - R12d live opt-in checklist (MAJOR) — separate gate.
- Future lane (deferred): email-verify unlock for `/killswitch lock`,
  multi-machine cache invalidation via Redis pub/sub.
