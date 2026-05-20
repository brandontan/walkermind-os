# WARP•FORGE REPORT — fix-drop-access-tier-warp50

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** migrations/ SQL files only
**Not in Scope:** Python code changes, frontend, new features

---

## 1. What Was Built

- Created `044_drop_access_tier.sql` per issue spec (single `ALTER TABLE users DROP COLUMN IF EXISTS access_tier;` statement).
- Audited all `.py` files under `projects/polymarket/crusaderbot/` for `access_tier` references.
- Verified migration 031 step 5 patch (from WARP-49) is still correct.

---

## 2. Current System Architecture

No architecture changes. SQL-only deliverable. Migration pipeline unchanged.

**Apply order:** 031 (already mostly applied; only step 2 live feed pending) → 044.

⚠️ 044 must NOT be applied to Supabase until the Python `access_tier` references listed in section 6 are migrated to the role-based model. Applying 044 against the current codebase will break LIVE TRADING GUARDS, user creation, the risk gate, the admin API, the operator allowlist, and multiple background jobs.

---

## 3. Files Created / Modified

| Action  | File |
|---------|------|
| CREATED | `projects/polymarket/crusaderbot/migrations/044_drop_access_tier.sql` |
| CREATED | `projects/polymarket/crusaderbot/reports/forge/fix-drop-access-tier-warp50.md` |

No other files modified.

---

## 4. Migration 044 Content (confirmed)

```sql
-- Migration 044: Drop access_tier column from users table
-- access_tier is obsolete — access control is now role-based (admin/user).
-- Safe to run: column is no longer referenced in any Python code or migration.
-- Idempotent: IF EXISTS guard prevents error on re-run.

ALTER TABLE users DROP COLUMN IF EXISTS access_tier;
```

---

## 5. Migration 031 Step 5 — confirmed clean

Current content at `projects/polymarket/crusaderbot/migrations/031_signal_scanner_user_enrollment.sql:72`:

```sql
-- 5. access_tier removed — role-based scope (admin/user) handles access. No action needed.
```

Patched by WARP-49 (PR #1216, merged). No further action needed on 031.

---

## 6. Python Code Audit — RESULT: **P1 BLOCKERS FOUND**

The issue's preamble for 044 says "column is no longer referenced in any Python code or migration." **This is FALSE.** 30 Python files reference `access_tier`. 16 are production paths (non-test). Dropping the column now will cause runtime failures on user creation, live trading gating, and admin APIs.

### Production code references (P1 — must migrate before applying 044)

| File | Lines | Surface |
|------|------|---------|
| `projects/polymarket/crusaderbot/users.py` | 71, 82, 84, 189, 198 | INSERT users + monotonic UPDATEs |
| `projects/polymarket/crusaderbot/scheduler.py` | 244, 286, 314 | SELECT in scheduler tick + ctx instantiation |
| `projects/polymarket/crusaderbot/services/tiers.py` | 4 | Docstring (low risk; cosmetic) |
| `projects/polymarket/crusaderbot/services/user_service.py` | 21, 23, 31, 44, 59, 72, 78, 91, 97 | INSERT/SELECT/UPDATE with audit; `update_access_tier` API |
| `projects/polymarket/crusaderbot/services/copy_trade/monitor.py` | 290, 481 | SELECT join + ctx field |
| `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` | 143, 398, 490 | Scanner SELECT + ctx instantiation |
| `projects/polymarket/crusaderbot/services/trade_engine/engine.py` | 77, 184, 288 | `SignalCtx.access_tier: int` dataclass field |
| `projects/polymarket/crusaderbot/api/admin.py` | 39, 41, 75, 83, 164 | Admin dashboard counts + user create endpoint |
| `projects/polymarket/crusaderbot/bot/middleware/access_tier.py` | (file-level) | `require_access_tier` decorator; the entire module is built on this |
| `projects/polymarket/crusaderbot/domain/activation/live_checklist.py` | 187, 191 | `SELECT access_tier FROM users` (live gate check 8) |
| `projects/polymarket/crusaderbot/domain/risk/gate.py` | 24, 140, 242, 243 | Risk gate `access_tier < 3` block (LIVE mode) |
| `projects/polymarket/crusaderbot/domain/execution/live.py` | 50, 70, 71, 80, 140 | `assert_live_guards(access_tier, ...)` — **LIVE TRADING GUARD** |
| `projects/polymarket/crusaderbot/domain/execution/router.py` | 27, 35, 57 | Router passes access_tier to live engine |
| `projects/polymarket/crusaderbot/domain/execution/parity.py` | 57, 82, 128 | Parity test infrastructure (≥4 for live) |
| `projects/polymarket/crusaderbot/scripts/seed_demo_data.py` | 204 | INSERT for demo users |
| `projects/polymarket/crusaderbot/scripts/seed_operator_tier.py` | 5, 10, 114, 125, 126, 131, 134, 135, 143, 158, 166, 171, 172 | Entire purpose is seeding `access_tier`; ON CONFLICT/GREATEST logic |

### Test references (must update once production paths are migrated)

`tests/test_access_tiers.py`, `tests/test_users.py`, `tests/test_signal_following.py`, `tests/test_signal_scan_job.py`, `tests/test_seed_operator_tier.py`, `tests/test_preset_system.py`, `tests/test_portfolio_charts_insights.py`, `tests/test_pipeline_runtime_hardening.py`, `tests/test_phase5j_emergency.py`, `tests/test_phase5h_onboarding.py`, `tests/test_phase5g_customize_wizard.py`, `tests/test_phase5f_copy_wizard.py`, `tests/test_phase5e_copy_trade.py`, `tests/test_phase5d_grid_menu_split.py`, `tests/test_live_opt_in_gate.py`, `tests/test_live_execution_rewire.py`, `tests/test_live_checklist.py`, `tests/test_isolation_audit.py`, `tests/test_fast_track_b.py`, `tests/test_fast_track_a.py`, `tests/test_fallback.py`, `tests/test_copy_trade.py`, `tests/test_activation_handlers.py`

---

## 7. What Is Working

- Migration 044 file content matches the issue spec exactly.
- Migration 031 step 5 patch from WARP-49 is intact at the expected line.
- The forge audit completed across all `.py` files under the project root.

---

## 8. Known Issues

**P1: Python code is NOT clean for `access_tier` removal.** Live trading guard (`domain/execution/live.py:assert_live_guards`) and risk gate (`domain/risk/gate.py`) both check `access_tier` integer thresholds (≥4 for LIVE, ≥3 for paper). These are safety-critical paths. Dropping the column drops these guards.

**Recommendation:** Do NOT apply 044 to Supabase until a separate lane migrates the Python production paths above to the role-based model. After Python migration, also update tests and the dataclass `SignalCtx.access_tier` field.

**Operational gap noted (out of scope here):**
Migration 031 step 2 (live feed seed) is still missing on Supabase production per the WARP-49 escalation diagnostic. That gap is independent of WARP-50 and should be closed in its own lane.

---

## 9. What Is Next

```text
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/fix-drop-access-tier-warp50.md
Tier: MINOR
```

**Apply order recommendation:** 031 → 044 — but **HOLD 044** until the P1 Python references in section 6 are migrated.

GATE + Mr. Walker handle Supabase execution per issue spec. No further FORGE action required on this lane.
