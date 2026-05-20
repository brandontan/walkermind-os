# WARP•FORGE REPORT — fix-migrations-warp49

**Validation Tier:** MINOR
**Claim Level:** NARROW INTEGRATION
**Validation Target:** migrations/027–031 SQL files only
**Not in Scope:** Python code, frontend, new schema changes, migration 024 (already applied)

---

## 1. What Was Built

Audit of migrations 027–031 for stale `access_tier` references. One blocker found and patched in-place in 031. No structural changes to any migration.

---

## 2. Current System Architecture

No architecture changes. Migration pipeline unchanged. Latest applied migration: 043. Migrations 027–031 are pending Supabase production application.

Schema truth established from migrations 032–043: no migration in that range touches `users.access_tier` or `users.role`. The column removal occurred outside the migration files (directly in Supabase).

---

## 3. Files Created / Modified

| Action   | File |
|----------|------|
| PATCHED  | `projects/polymarket/crusaderbot/migrations/031_signal_scanner_user_enrollment.sql` |
| CREATED  | `projects/polymarket/crusaderbot/reports/forge/fix-migrations-warp49.md` |

---

## 4. Per-Migration Status

| Migration | Status    | Detail |
|-----------|-----------|--------|
| 027       | CONFIRMED CLEAN | Adds `notifications_on` BOOLEAN to `user_settings`. No `access_tier` reference. |
| 028       | OUT OF SCOPE | Not in audit range (027/029/030/031 per issue). |
| 029       | CONFIRMED CLEAN | Creates `portfolio_snapshots`, `system_alerts`, and NOTIFY triggers. No `access_tier` reference. |
| 030       | CONFIRMED CLEAN | Adds `metadata` JSONB to `job_runs`. No `access_tier` reference. |
| 031       | PATCHED | Step 5 removed (see below). Steps 1–4 verified CLEAN. |

---

## 5. What Is Working

**Migration 031 — patch detail**

Removed (hard blocker):
```sql
-- 5. Align access_tier with role model — paper is open to all users
UPDATE users SET access_tier = 3 WHERE access_tier < 3;
```

Replaced with:
```sql
-- 5. access_tier removed — role-based scope (admin/user) handles access. No action needed.
```

`role` column nullability was NOT confirmed from migrations 032–043 (no migration in that range adds or alters `users.role`). Per issue instructions: no `UPDATE users SET role = ...` added.

**Migration 031 Steps 1–4 — schema verification**

Step 1 & 2 — `signal_feeds` INSERT:
- Columns used: `id, name, slug, operator_id, status, description, subscriber_count, is_demo, created_at, updated_at`
- All present: `id/name/slug/operator_id/status/description/subscriber_count/created_at/updated_at` from 010, `is_demo` from 014 ✓

Step 3 — `user_strategies` INSERT:
- Columns used: `user_id, strategy_name, weight, enabled, created_at`
- Identical pattern used in 024 step 5 (already applied without issue) ✓

Step 4 — `user_signal_subscriptions` INSERT:
- Columns used: `user_id, feed_id, subscribed_at, is_demo`
- `unsubscribed_at IS NULL` guard column present from 010 ✓
- `is_demo` added by 014 ✓

---

## 6. Known Issues

**024 step 4 has an identical `access_tier` UPDATE** (`UPDATE users SET access_tier = 3 WHERE access_tier < 3`). This is outside the declared scope (027–031) and was already applied. Flagged for WARP🔹CMD awareness — if 024 ever needs to be replayed, it will hit the same blocker.

No other issues found.

---

## 7. What Is Next

```
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/fix-migrations-warp49.md
Tier: MINOR
```

GATE + Mr. Walker handle Supabase execution of 027–031. No further FORGE action required on this lane.
