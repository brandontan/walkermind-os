# WARP•FORGE REPORT — fix-active-issues

**Branch:** WARP/fix-active-issues
**Date:** 2026-05-20 15:30 WIB
**Validation Tier:** MINOR
**Claim Level:** FOUNDATION
**Validation Target:** Linear issue status sync for WARP-35 and WARP-37
**Not in Scope:** Code changes, migrations, runtime behavior

---

## 1. What Was Built

State sync lane: verified that WARP-35 and WARP-37 fixes are present in `main`, then closed both Linear issues from `In Progress` → `Done` with completed task checklists.

---

## 2. Current System Architecture

No architecture changes. CrusaderBot runtime unchanged.

---

## 3. Files Created / Modified

- `projects/polymarket/crusaderbot/reports/forge/fix-active-issues.md` — this report (created)
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure entry appended
- Linear WARP-35 — status updated to Done, description updated with fix details and checked tasks
- Linear WARP-37 — status updated to Done, description updated with fix details and checked tasks

---

## 4. What Is Working

**WARP-35** — DataError: date string to asyncpg (1-min job)
- Root: `copy_trade_monitor.run_once` (COPY_TRADE_MONITOR_INTERVAL=60s)
- Functions: `_get_daily_spend` / `_record_spend` in `services/copy_trade/monitor.py`
- Fix in main: `date.today()` returns `datetime.date` — correct, no `.isoformat()` call
- Regression tests in `tests/test_copy_trade.py` (commit `7f14c42d`, direct-apply 2026-05-19)
- Linear WARP-35: Done ✓

**WARP-37** — BadRequest: Telegram edit_message_text no-op
- Root: `bot/handlers/setup.py → set_risk` and 5 other inline-edit handlers
- Fix in main: `except BadRequest as e: if "not modified" not in str(e).lower(): raise` guard in all 6 handlers
  - `setup.py` ×5: `set_risk` (line 269), `set_category` (line 295), `set_mode` (line 329) + 2 others
  - `settings.py` ×1: `_render_hub` (line 128)
- Commits `088bad4` + `843bb6c` (direct-apply 2026-05-19/20)
- Linear WARP-37: Done ✓

---

## 5. Known Issues

None introduced by this lane.

---

## 6. What Is Next

**Suggested Next Step:** WARP🔹CMD review of open WARP-45 PR (fix-sentry-p1-runtime-bugs) — asyncpg JSONB-as-str fix for signal_scan_job.py. Redeploy on Fly.io after merge.
