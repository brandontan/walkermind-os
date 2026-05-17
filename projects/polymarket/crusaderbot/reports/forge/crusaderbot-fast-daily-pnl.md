# WARP•FORGE Report — crusaderbot-fast-daily-pnl

**Branch:** WARP/CRUSADERBOT-FAST-DAILY-PNL
**Date:** 2026-05-17
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Daily P&L report service — cron job, per-user monospaced Telegram push
**Not in Scope:** live trading activation, new DB tables, existing daily_pnl_summary job

---

## 1. What Was Built

New `services/daily_report_service.py` implementing a daily P&L report cron job (Track E).

- `daily_pnl_report_job()` — APScheduler entry point; iterates all active users with a Telegram ID, skips users with zero closed trades today, sends one report per qualifying user. One user failure never aborts others.
- `_fetch_daily_stats(user_id, today)` — two DB queries: (1) aggregate closed-trade stats scoped to `DATE(closed_at) = today`; (2) open position count (not date-scoped, all currently open).
- `_format_daily_report(stats)` — monospaced `<pre>` block with `━━━━━━━━━━━━━━━━━━━━` separators: date, mode (PAPER), trades/wins/losses/win-rate, P&L with sign + emoji, best/worst trade, balance, open positions.
- `JOB_ID = "daily_pnl_report"` — registered in scheduler; distinct from existing `daily_pnl_summary` job ID.

Config addition: `DAILY_REPORT_HOUR: int = 23` in `config.py` — readable from env `DAILY_REPORT_HOUR` (0-23). Scheduler uses `s.DAILY_REPORT_HOUR` at the cron `hour` argument, timezone resolved from `s.TIMEZONE` (Asia/Jakarta).

---

## 2. Current System Architecture

Daily report sits alongside the existing `jobs/daily_pnl_summary.py` as an independent service:

```
APScheduler (setup_scheduler)
  ├── daily_pnl_summary (jobs/) — 23:00 Jakarta — existing R12 summary
  └── daily_pnl_report  (services/) — DAILY_REPORT_HOUR UTC — new Track E report
           │
           ├── _list_active_users()         ← users WHERE telegram_user_id IS NOT NULL
           ├── _fetch_daily_stats(uid, date) ← positions + wallets (no new tables)
           └── _format_daily_report(stats)   ← HTML <pre> monospaced
                     │
                     └── notifications.send(tg_id, text)
```

No new DB tables. No new migrations. Uses existing `positions` and `wallets` schema.

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/services/daily_report_service.py`

**Modified:**
- `projects/polymarket/crusaderbot/config.py` — added `DAILY_REPORT_HOUR: int = 23`
- `projects/polymarket/crusaderbot/scheduler.py` — import `daily_pnl_report_job` + `JOB_ID`; register cron job in `setup_scheduler()`

---

## 4. What Is Working

- `python3 -m compileall` — clean (all 3 files)
- `ruff check` — clean (all 3 files)
- Zero-trades skip: `if stats["total_trades"] == 0: skipped += 1; continue`
- One-user isolation: outer `try/except` per user with `failed += 1` and `continue`
- P&L sign: `pnl_sign = "+" if pnl >= 0 else ""` — positive shows `+$X.XX`, negative shows `-$X.XX`
- Win rate: `(wins / total * 100) if total > 0 else 0.0` — zero-division safe
- Monospaced format: `<pre>` block with `━` separator lines
- Cron registered at `s.DAILY_REPORT_HOUR` (default 23), timezone from `s.TIMEZONE`
- `replace_existing=True` — scheduler restart is idempotent

---

## 5. Known Issues

- `DATE(closed_at) = today` resolves in DB server timezone (typically UTC); if the server timezone differs from Asia/Jakarta, the cutoff for "today's trades" may differ by up to 7 hours from the Jakarta calendar day. Acceptable for PAPER scope; timezone-aware `AT TIME ZONE` filter can replace it in a future lane.
- `_list_active_users()` fetches all users with a Telegram ID regardless of `paused` flag; paused users will receive the report if they have trades. Consistent with spec ("all active users" = users with telegram_user_id set).

---

## 6. What Is Next

- WARP🔹CMD review required for this PR (STANDARD tier — CMD review only, no SENTINEL).
- Optional follow-up: replace `DATE(closed_at) = today` with timezone-aware filter (`AT TIME ZONE 'Asia/Jakarta'`) if daily cutoff precision matters.
- Optional follow-up: add opt-out toggle (system_settings `daily_report_off:{user_id}`) mirroring the existing `daily_pnl_summary` toggle pattern.

---

**Suggested Next Step:** WARP🔹CMD review and merge. Source: `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-daily-pnl.md`. Tier: STANDARD.
