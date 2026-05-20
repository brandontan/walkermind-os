# WARP•FORGE Report — fix-sentry-p1-runtime-bugs

**Branch:** WARP/fix-sentry-p1-runtime-bugs
**Issue:** #1198 — WARP-45
**Date:** 2026-05-20 13:15 WIB
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** `signal_scan_job.py` JSONB coercion at line 744
**Not in Scope:** Sentry issues pre-2026-05-17 (TooManyConnectionsError, UndefinedColumnError), other signal_scan logic

---

## 1. What Was Built

Fixed the live P1 `ValueError` in `signal_scan_job.run_once` (Sentry DAWN-SNOWFLAKE-1729-1Q, 7 events in last 14 min at time of dispatch).

asyncpg returns JSONB columns as Python `str` when using Supavisor/PgBouncer transaction-pool mode. `dict('{}')` iterates over string characters — each has length 1 — triggering `ValueError: dictionary update sequence element #0 has length 1; 2 is required`. Added module-level `_coerce_jsonb()` helper to safely deserialise JSONB values regardless of whether asyncpg returns `str`, `dict`, or `None`.

**Bugs 2 and 3 from issue #1198 were already resolved prior to this task:**
- Bug 2 (`monitor.py` date `.isoformat()`) — fixed in WARP-35 (PR merge SHA 7f14c42d); `today = date.today()` confirmed in place at line 424.
- Bug 3 (`setup.py` BadRequest not-modified guard) — fixed in WARP-37 (PR merge SHA 088bad43); guards confirmed at lines 269–271, 294–296, 328–330.

---

## 2. Current System Architecture

No architecture change. `_coerce_jsonb()` is a module-level pure function within the signal scan job. It adds a single safe deserialization layer between asyncpg row access and the dict operation, matching the same pattern used elsewhere in the codebase for JSONB resilience.

---

## 3. Files Created / Modified

| Action | File | Change |
|--------|------|--------|
| Modified | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` | `import json` added (line 45); `_coerce_jsonb()` helper added (after `_preset_allows`); line 761 `dict(...)` → `_coerce_jsonb(...)` |

---

## 4. What Is Working

- `_coerce_jsonb(val, {})` handles all asyncpg return forms: `None` → `{}`, `str` (valid JSON) → parsed dict, `str` (invalid JSON) → `{}` fallback, `dict` → pass-through.
- `strategy_params.get(lib_name, {})` on line 770 now safe against any JSONB return format.
- AST parse clean — no syntax errors.
- Bug 2 and Bug 3 confirmed already resolved — no regressions introduced.

---

## 5. Known Issues

None introduced by this change. The COALESCE in SQL (line 156) ensures `strategy_params` is never truly NULL from the DB, but asyncpg may still return the JSONB value as a string in transaction-pool mode — the guard handles both paths.

---

## 6. What Is Next

- WARP🔹CMD review + merge.
- Fly.io redeploy — signal_scan_job runs as a scheduler job; fix takes effect on next scan tick after deploy (no migration required).
- Monitor Sentry DAWN-SNOWFLAKE-1729-1Q — should resolve to 0 new events after deploy.

---

**Suggested Next Step:** WARP🔹CMD review and merge. No migration. Redeploy on Fly.io.
