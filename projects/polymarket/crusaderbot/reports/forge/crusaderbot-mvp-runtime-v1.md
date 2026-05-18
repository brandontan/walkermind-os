# WARP•FORGE Report — crusaderbot-mvp-runtime-v1

**Branch:** WARP/crusaderbot-mvp-runtime-v1
**Date:** 2026-05-16
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** Tier gate removal from all paper-mode paths; admin panel cleanup
**Not in Scope:** `api/admin.py` REST status counts (monitoring-only); `user_tiers` table; `assert_live_guards`; live risk gate (`_passes_live_guards` requires `access_tier >= 4`, step-3 block `access_tier < 3` — both in gate.py); activation guard flags

---

## 1. What Was Built

Removed all legacy integer tier gates from paper-mode paths. The MVP role model is now **admin + user** only. Any registered user with `auto_trade_on=TRUE` can participate in paper trading without needing `access_tier >= 2/3`.

Changes delivered:
- **scheduler.py** — removed Tier 3 auto-promotion on deposit confirmation; removed `access_tier >= 3` filter from `run_signal_scan()` user query; simplified deposit notification (no tier messaging); removed `min_deposit` variable
- **signal_scan/signal_scan_job.py** — removed `AND u.access_tier >= 3` from `_load_enrolled_users()` WHERE clause; updated docstring
- **jobs/daily_pnl_summary.py** — removed `WHERE access_tier >= 2` from recipient user list
- **jobs/weekly_insights.py** — removed `WHERE access_tier >= 2 AND` from recipient user list
- **bot/middleware/tier_gate.py** — replaced full decorator with no-op passthrough (import compat preserved)
- **bot/handlers/admin.py** — `/status` now shows `Users · Admins` instead of `Users · Funded · Live`; `active_users` in ops dashboard counts all users; kill-switch broadcast targets `auto_trade_on=TRUE` users only

---

## 2. Current System Architecture

```
Telegram /start → upsert_user() → paper mode open (all users)

APScheduler (60s) → market_signal_scanner → signal_publications
APScheduler (180s) → sf_scan_job._load_enrolled_users()
    WHERE strategy_name='signal_following' AND enabled=TRUE
      AND auto_trade_on=TRUE AND paused=FALSE   ← no tier filter
    → TradeEngine → paper orders

APScheduler (deposit) → watch_deposits()
    → ledger.credit_in_conn() → deposit confirmed notification
    (no tier auto-promotion)

APScheduler (23:00 WIB) → daily_pnl_summary → all users
APScheduler (weekly) → weekly_insights → all users with telegram_user_id

Risk gate (UNCHANGED):
    domain/risk/gate.py: access_tier < 3 → blocks live only
    domain/execution/live.py: assert_live_guards() → NEVER bypassed

Admin role (UNCHANGED):
    bot/roles.py: is_admin_full() → OPERATOR_CHAT_ID OR user_tiers ADMIN
    bot/middleware/access_tier.py: require_access_tier('ADMIN') → still wired
```

---

## 3. Files Created / Modified

| Action | Path |
|---|---|
| MODIFIED | `projects/polymarket/crusaderbot/scheduler.py` |
| MODIFIED | `projects/polymarket/crusaderbot/services/signal_scan/signal_scan_job.py` |
| MODIFIED | `projects/polymarket/crusaderbot/jobs/daily_pnl_summary.py` |
| MODIFIED | `projects/polymarket/crusaderbot/jobs/weekly_insights.py` |
| REPLACED | `projects/polymarket/crusaderbot/bot/middleware/tier_gate.py` |
| MODIFIED | `projects/polymarket/crusaderbot/bot/handlers/admin.py` |
| CREATED  | `projects/polymarket/crusaderbot/reports/forge/crusaderbot-mvp-runtime-v1.md` |
| UPDATED  | `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` |
| UPDATED  | `projects/polymarket/crusaderbot/state/CHANGELOG.md` |

---

## 4. What Is Working

- `_load_enrolled_users()` returns all users with `signal_following` enrolled and `auto_trade_on=TRUE` — no tier filter
- `run_signal_scan()` processes all auto-trade users — no tier filter
- Daily PNL summary and weekly insights delivered to all registered users with `telegram_user_id`
- Deposit confirmation sends "Deposit confirmed: $X USDC" — no tier messaging
- Admin `/status` shows `Users: N · Admins: M` — correct for two-role model
- `require_tier()` is a no-op passthrough — all callers still import and run with zero runtime effect
- `assert_live_guards()` untouched — live trading still fully gated
- `access_tier` column still read by live risk gate (GateContext) — kept in SELECT where needed
- `python -m compileall` passes clean on full crusaderbot package

---

## 5. Known Issues

- `api/admin.py` REST status endpoint still reports `funded` and `live` tier counts (out of scope; monitoring-only, does not gate any user action)
- `domain/activation/live_checklist.py:188` docstring references `access_tier >= 4` — informational, no code impact
- `users.access_tier` DB column is kept; existing rows retain their values but the column has no runtime effect on paper paths
- `user_tiers` table kept — still used by `is_admin_full()` for ADMIN string tier check

---

## 6. What Is Next

- WARP•SENTINEL validation required (MAJOR tier): confirm paper scan picks up all users regardless of `access_tier`; confirm `assert_live_guards` still raises; confirm admin panel counts correct
- Apply migration 027 (`notifications_on`) to production before Fly.io deploy
- Deploy to Fly.io (PAPER ONLY — activation guards remain OFF)
- Wire `require_access_tier('ADMIN')` onto admin command handlers (separate lane)

---

**Suggested Next Step:** WARP•SENTINEL validation on WARP/crusaderbot-mvp-runtime-v1 — confirm `_load_enrolled_users()` has no tier filter, `run_signal_scan()` has no tier filter, `assert_live_guards()` still raises for live, admin `/status` shows Admins count.
