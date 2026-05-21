# WARP-51 — SENTINEL Audit Report

Branch (audited): `WARP/warp51-drop-access-tier`
Head SHA: `7c3f6c43a004328e864d80457fdc946cfc55f9ab`
PR: #1224
Validation Tier: MAJOR
Claim Level: NARROW INTEGRATION
Sentinel Issue: #1225
Auditor: WARP•SENTINEL
Audit Date: 2026-05-21 (Asia/Jakarta)

---

## 1. Environment

| Slot | Value |
|---|---|
| Env tier | dev (audit-only; no live infra writes) |
| Infra checks | warn-only (dev posture) |
| Risk checks | ENFORCED (read-only grep + diff inspection) |
| Telegram checks | warn-only (dev posture) |
| Runtime | static audit on PR head SHA |
| `ENABLE_LIVE_TRADING` | OFF (preserved — not touched by PR) |

---

## 2. Test Plan

8 audit targets dispatched by WARP🔹CMD (Sentinel Issue #1225). Scope is **NARROW INTEGRATION** — auditor verifies the bounded claim "every `.py` writer/reader of `users.access_tier` removed + migration `044` re-enabled" without re-validating execution / risk core (out of scope per PR brief).

| Target | Subject | Verification method |
|---|---|---|
| S1 | Residual `access_tier` column refs in `.py` | grep with whitelist exclusion |
| S2 | Migration `044_drop_access_tier.sql` safety | file presence + content read |
| S3 | `/allowlist` uses `set_role` not `force_set_tier` | grep `bot/handlers/admin.py` |
| S4 | Deleted files actually gone + `fly.toml` | `ls` + `grep release_command` |
| S5 | `set_tier` / `force_set_tier` fully removed | repo-wide grep for def + call sites |
| S6 | Test suite integrity (1487 passed) | report claim + CI status cross-check |
| S7 | `bot/middleware/access_tier.py` content | line-by-line read |
| S8 | NARROW INTEGRATION scope boundary | `git diff --name-only` against `domain/execution`, `domain/risk`, `domain/signal` |

### Phase 0 — Pre-test

| Check | Result | Evidence |
|---|---|---|
| Forge report present + 6 mandatory sections | PASS | `projects/polymarket/crusaderbot/reports/forge/warp51-drop-access-tier.md` — all 6 sections + tier/claim/target/not-in-scope metadata declared |
| `PROJECT_STATE.md` updated by FORGE | PASS (P2 process note) | `state/PROJECT_STATE.md:74` carries WARP-51 NEXT PRIORITY entry. GATE flagged FORGE-touched state as P2 (GATE owns post-merge sync); content is correct so no rollback |
| No `phase*/` folders | PASS | Repo scan clean |
| Hard delete policy | PASS | `scripts/seed_operator_tier.py` + `tests/test_seed_operator_tier.py` confirmed absent on disk; `migrations/044_drop_access_tier.sql.disabled` removed (rename, not copy) |
| Implementation evidence for critical layers | PASS | INSERT path verified in `users.py:71–72`, `services/user_service.py:32–36`; `set_role` defined `users.py:181–188`; migration content valid |
| Branch format `WARP/{feature}` | PASS | `WARP/warp51-drop-access-tier` matches authoritative format |
| CI green | PASS | Per WARP🔹GATE check CHECK-14 (1487 passed, lint clean) |

Phase 0: **CLEAR — proceed to audit phases.**

---

## 3. Findings (S1–S5)

### S1 — Zero residual `access_tier` column refs

Command:
```
grep -RnE "access_tier" --include="*.py" projects/polymarket/crusaderbot/ \
  | grep -vE "(bot/middleware/access_tier\.py|tests/test_access_tiers\.py|tests/test_isolation_audit\.py)"
```

Result: **zero lines** (grep exit 1).

Whitelisted file counts (informational, all expected):
- `bot/middleware/access_tier.py`: 3 matches (file-path docstring + filename mentions; no column ref — see S7)
- `tests/test_access_tiers.py`: 7 matches (docstring-only per FORGE; coverage holds via role tests)
- `tests/test_isolation_audit.py`: 6 matches (audit fixture path strings — not column writes)

**Verdict: PASS.** No `.py` writer/reader of the column remains in production paths.

### S2 — Migration 044 safety

File: `projects/polymarket/crusaderbot/migrations/044_drop_access_tier.sql` (680 bytes; `.disabled` variant **absent**).

Content (line 14):
```
ALTER TABLE users DROP COLUMN IF EXISTS access_tier;
```

Properties:
- Idempotent (`IF EXISTS`) — safe re-run after partial apply or rollback.
- Single destructive op only — no cascading drops, no data export, no row mutations.
- Header documents the WARP-50b crash-loop history and the WARP-51 re-enable rationale.
- Will execute automatically via `database.run_migrations()` on next Fly deploy.

Crash-loop recurrence risk: **MITIGATED**. The prior failure was caused by live INSERT paths writing `access_tier=4` after the column dropped. S1 + S5 confirm those writers are gone.

**Verdict: PASS.**

### S3 — Admin promotion path

`projects/polymarket/crusaderbot/bot/handlers/admin.py`:

| Line | Evidence |
|---|---|
| 36 | `from ... import ... set_role, ...` (import swapped from `force_set_tier`) |
| 417 | `async def allowlist_command(...)` |
| 427 | Help text: `"/allowlist @username ... — promotes user to admin role."` |
| 446 | `await set_role(user["id"], "admin")` — the promotion call |
| 447–448 | `await audit.write(actor_role="operator", action="allowlist", user_id=user["id"], payload={"new_role": "admin"})` |

`force_set_tier` is not imported, not called, not referenced in this file.

**Verdict: PASS.** `/allowlist` is now a single-statement role promotion + structured audit row.

### S4 — Deleted files + `fly.toml`

| Target | Status |
|---|---|
| `scripts/seed_operator_tier.py` | DELETED (`ls`: No such file) |
| `tests/test_seed_operator_tier.py` | DELETED (`ls`: No such file) |
| `migrations/044_drop_access_tier.sql.disabled` | DELETED (rename, not copy) |
| `fly.toml [deploy].release_command` | REMOVED — `[deploy]` block now contains only `strategy = "immediate"` |

No orphan import of the deleted seeder remains (S5 confirms no `force_set_tier` / `set_tier` references repo-wide).

**Verdict: PASS.**

### S5 — `set_tier` / `force_set_tier` fully removed

Command:
```
grep -RnE "(def set_tier|def force_set_tier|force_set_tier\(|set_tier\()" \
  --include="*.py" projects/polymarket/crusaderbot/
```

Result: **zero lines.**

The sole remaining writer of elevated-user state is `users.set_role(user_id, role)` (`users.py:181`), which:
- Validates `role in {"admin", "user"}` (raises `ValueError` on unknown — line 184).
- Executes `UPDATE users SET role=$2 WHERE id=$1` (line 188).
- Is called from exactly one production handler: `bot/handlers/admin.py:446` (`/allowlist`).

**Verdict: PASS.**

---

## 4. Findings (S6–S8)

### S6 — Test suite integrity

| Source | Claim |
|---|---|
| FORGE report (`reports/forge/warp51-drop-access-tier.md:99`) | `1487 passed, 1 skipped, 0 failed` |
| GATE check CHECK-14 (PR #1224 comment 4503925688) | CI: `success` — 1487 passed |
| Delta from WARP-50b 1512 baseline | -25 (= 24 deleted `test_seed_operator_tier.py` + 1 env skip) |
| Sentinel local pytest run | Not executed — sandbox has no `pytest` module installed. Audit relies on CI signal + FORGE evidence per CLAUDE.md "code is truth" rule (test counts cross-validated). |

Coverage gap risk: Deleted tests covered a deleted script (`seed_operator_tier.py`). No active runtime path lost test coverage — the role-based promotion path (`set_role` + `/allowlist`) is exercised by `tests/test_users.py` and `tests/test_access_tiers.py` (untouched in logic; docstring update only).

**S6 Verdict: PASS** (advisory note logged — see Fix Recommendations P3).

### S7 — `bot/middleware/access_tier.py` content

96-line file, docstring confirms intent:
- Lines 4–6: docstring shows usage example — `from ..middleware.access_tier import require_role; @require_role('admin')`.
- Lines 14–15: `"The file name is retained as access_tier.py for import-path stability; the legacy integer access_tier scheme has been removed."`
- Line 57: `def require_role(required_role: str) -> Callable[[HandlerFn], HandlerFn]:` — role string gate, not integer tier.
- Line 65: validates against `VALID_ROLES` set.

Greps for integer-tier comparisons (`tier <`, `tier ==`, `tier >`, `tier <=`, `tier >=`, `tier !=`, `access_tier =`) all return zero hits inside this file. Only the historical filename token survives.

**S7 Verdict: PASS.** Body is fully role-based; file is held under its current name purely for import-path stability per WARP🔹CMD directive.

### S8 — NARROW INTEGRATION scope boundary

`git diff --name-only 39460c5..7c3f6c4` filtered to execution / risk / signal domains:

```
(empty)
```

No file under `projects/polymarket/crusaderbot/domain/execution/`, `domain/risk/`, or `domain/signal/` was touched in this PR.

Full diff (32 files) is confined to:
- 2 INSERT/SELECT call sites (`users.py`, `services/user_service.py`)
- 1 admin handler (`bot/handlers/admin.py`)
- 1 API comment (`api/admin.py`)
- 1 demo seeder (`scripts/seed_demo_data.py`)
- 1 docstring (`services/tiers.py`)
- 16 test fixtures (fixture key removal only — no logic changes)
- 1 deploy config (`fly.toml`)
- 1 migration (`044_drop_access_tier.sql` renamed from `.disabled`)
- 1 runbook (`kill-switch-procedure.md`)
- 3 state files (`PROJECT_STATE.md`, `WORKTODO.md`, `CHANGELOG.md` — flagged P2 by GATE)
- 1 forge report

Execution engine, capital allocation, order pipeline, risk gate logic, kill switch, activation guards — all untouched.

**S8 Verdict: PASS.** Scope boundary respected.

---

## 5. Critical Issues

**None found.**

No P0 or P1 findings. P2/P3 advisories are listed under Fix Recommendations and are non-blocking.

---

## 6. Stability Score Breakdown

| Dimension | Weight | Score | Notes |
|---|---|---|---|
| Architecture | 20 | 20 | Single source of truth for elevated user state (`set_role`). No shims. No `phase*/`. |
| Functional | 20 | 20 | INSERT/SELECT/UPDATE paths verified at file:line; `/allowlist` audit row well-formed. |
| Failure modes | 20 | 19 | Migration is idempotent. Crash-loop recurrence path closed. -1 for pytest not re-run in sandbox (advisory). |
| Risk | 20 | 20 | NARROW scope; no execution/risk/capital path touched. Live guards unchanged. |
| Infra + Telegram | 10 | 10 | `fly.toml [deploy].release_command` removed; `/allowlist` handler clean. |
| Latency | 10 | 10 | No hot-path changes; INSERT shape simplified (one fewer column). |

**TOTAL: 99 / 100**

---

## 7. Go-Live Status

```
SENTINEL VERDICT: APPROVED
Score: 99/100
Critical Issues: 0
```

**Reasoning:**

WARP-51 delivers a clean, scope-bound removal of the dead `users.access_tier` column writes and re-enables migration 044 to drop the column on next Fly deploy. The prior crash-loop scenario (PR #1223) cannot recur because every Python INSERT path that previously wrote `access_tier=4` has been verified absent (S1 + S5). The admin promotion path now flows exclusively through `set_role` with structured audit logging (S3). No execution, risk, capital, or kill-switch surface was touched (S8). Tests pass per CI signal (S6). The `bot/middleware/access_tier.py` filename is retained for import-path stability but is fully role-based internally (S7).

Migration 044's `DROP COLUMN IF EXISTS` is idempotent and safe to apply automatically on the next deploy. The PR is mergeable on its own merits.

**NEXT GATE:** Return to WARP🔹CMD for final merge decision. Post-merge: Fly redeploy will execute `044_drop_access_tier.sql` via `database.run_migrations()`.

---

## 8. Fix Recommendations

Priority ordered. None block merge.

**P2 — non-blocking, post-merge cleanup**
1. **State-file ownership.** FORGE touched `CHANGELOG.md`, `PROJECT_STATE.md`, `WORKTODO.md` in this PR. Per AGENTS.md, GATE owns post-merge sync of these files. Content here is accurate, so no rollback. GATE will overwrite with canonical sync after merge — no action required from SENTINEL or FORGE.
2. **Forge report branch line.** GATE flagged that the FORGE report omits an explicit `Branch: WARP/warp51-drop-access-tier` header line. Content is otherwise complete. Cosmetic only.

**P3 — backlog cleanup lanes (separate PRs)**
3. **Rename `bot/middleware/access_tier.py` → `bot/middleware/role_guard.py`.** Filename token is the last semantic carry-over of the legacy tier system. A grep-replace + import sweep, deferred per WARP🔹CMD scope decision.
4. **Remove legacy `bot/tier.py` integer enum (`Tier.BROWSE/ALLOWLISTED/FUNDED/LIVE`).** Already dead-code per FORGE report; can be deleted in a follow-up lane.
5. **Decide on `services/tiers.py` + `user_tiers` table.** Parallel string-tier system unrelated to `access_tier`; out of WARP-51 scope but worth a CMD-level decision.
6. **Sentinel sandbox parity.** Add `pytest` to the SENTINEL sandbox so future audits can re-run the suite locally instead of relying on CI cross-check.

---

## 9. Telegram Preview

Relevant user-facing surface for this PR is the `/allowlist` command. No dashboard or alert format changes.

### `/allowlist` flow (post-merge)

```
Operator > /allowlist @username
Bot      > ✅ @username (tg_id=...) promoted to admin role.

Audit log row written:
  action      = "allowlist"
  actor_role  = "operator"
  user_id     = <UUID>
  payload     = {"new_role": "admin"}
```

### Failure modes covered

| Input | Behavior |
|---|---|
| `/allowlist` (no arg) | Usage hint with HTML-escaped placeholder (line 426–427) |
| `/allowlist @unknown` | User-not-found message — no DB write, no audit row |
| `/allowlist <bad-id>` | Same not-found path |
| `set_role` with invalid role string | `ValueError` raised before SQL — caught + logged via structlog |

### Commands unchanged by this PR

- `/admin status` — paper-mode HUD (untouched)
- Risk gate kill switch — untouched
- `assert_live_guards` — untouched
- Live opt-in checklist — untouched

---

## 10. Deferred Backlog

- Independent pytest re-run in sandbox (S6 advisory — relied on CI cross-check this time).
- `bot/middleware/access_tier.py` filename rename (P3).
- `bot/tier.py` legacy enum deletion (P3).
- `services/tiers.py` / `user_tiers` table fate (P3).
- Post-deploy verification: confirm `044_drop_access_tier.sql` ran on Fly and `users.access_tier` column is physically gone — owned by WARP🔹CMD post-merge ops.
