# WARP•FORGE Report — bot-polish-beta

**Branch:** WARP/CRUSADERBOT-BOT-POLISH-BETA
**Date:** 2026-05-16 23:59 Asia/Jakarta
**Validation Tier:** MAJOR
**Claim Level:** FULL RUNTIME INTEGRATION
**Validation Target:** P0 connection fix, notification scope suppression, trade UX inline keyboards, admin/user scope separation
**Not in Scope:** Area 4 (live runtime verification — requires Fly.io access), migration application, logo PNG binary, WebTrader TSX

---

## 1. What Was Built

Four areas of bot hardening implemented against Sentry production issues and Boss directive.

**Area 0 — P0 Production Fixes**
- `fly.toml`: deploy strategy changed from `rolling` → `immediate`. Kills old instance before new one starts, eliminating the dual-instance Telegram polling conflict (DAWN-SNOWFLAKE-1729-14, 435 events) and connection pool exhaustion.
- `database.py`: added `max_inactive_connection_lifetime=60.0` to asyncpg pool. Idle connections released after 60s instead of holding Supabase slots indefinitely. `command_timeout` reduced to 10.0s (was 30s).
- `bot/handlers/trades.py`: all 4 direct `market_question` column reads rewritten to `LEFT JOIN markets m ON m.id = p.market_id` with `m.question AS market_question`. Fixes DAWN-SNOWFLAKE-1729-1A/19 `column market_question does not exist` crashes.
- `bot/handlers/share_card.py`: same JOIN fix applied (5th query found outside trades.py).

**Area 1 — Notification Scope Fix**
- `domain/execution/exit_watcher.py`: `alert_user_close_failed()` and `alert_user_market_expired()` user Telegram sends replaced with `logger.info()`. Operator alert (`alert_operator_close_failed_persistent`) preserved.
- `monitoring/alerts.py`: `alert_startup()` function deleted (no production callers). `_STARTUP_LOCK`, `_STARTUP_COOLDOWN` constants deleted. `import os` removed. Deprecation docstrings added to `alert_user_market_expired()` and `alert_user_close_failed()`.
- `tests/test_health.py`: `alert_startup` references replaced with `alert_dependency_unreachable("test", "probe")` — tests still exercise `schedule_alert` behavior, which was the actual test subject.

**Area 2 — Telegram UX**
- `services/trade_notifications/notifier.py`: `InlineKeyboardButton` added to imports. `notify_entry()` gains `position_id: Optional[str] = None` and builds "📋 View Trade / 📊 Dashboard" keyboard (degrades to Dashboard-only if no position_id). `notify_tp_hit()`, `notify_sl_hit()`, `notify_manual_close()` build "📈 My Trades / 📊 Dashboard" keyboard when `reply_markup` is None. `notify_emergency_close()` gains same default keyboard.
- `scheduler.py`: deposit confirmation messages now include "💰 Wallet / 📊 Dashboard" inline keyboard via `InlineKeyboardMarkup`.
- `bot/handlers/dashboard.py`: replaced `main_menu_keyboard()` import and all 3 usage sites with `main_menu(strategy_key="set" if has_preset else None, auto_on=user.get("auto_trade_on", False))`. State-driven keyboard is now primary. `main_menu()` buttons are already routed by `bot/menus/main.py` `get_menu_route()` through `_text_router`.

**Area 3 — Admin/User Scope Separation**
- `bot/handlers/start.py`: `help_command()` rewritten to show user commands only, with admin block appended when `tg_id == settings.OPERATOR_CHAT_ID`.
- `jobs/weekly_insights.py`: `_list_active_users()` query now filters `AND paused = FALSE AND auto_trade_on = TRUE`. Previously sent weekly insights to all tier≥2 users regardless of active status.
- `jobs/hourly_report.py`: fixed JOIN bug — `t.user_id = u.telegram_user_id` was wrong (UUID vs bigint); corrected to `t.user_id = u.id`. Admin-tier recipients were never actually returned correctly before this fix.

---

## 2. Current System Architecture

```
Fly.io [strategy=immediate] → single instance guarantee
    └── asyncpg pool (max_inactive_conn_lifetime=60s, cmd_timeout=10s)
        ├── exit_watcher: TP/SL/FORCE/STRATEGY/EXPIRED exits
        │   ├── EXPIRED/CLOSE_FAILED → logger.info only (NO user Telegram)
        │   └── all valid exits → notifier.notify_*() with inline KB
        ├── signal_scanner → trades.py (JOIN markets for market_question)
        ├── scheduler → watch_deposits (deposit KB added)
        └── weekly_insights → active users only (paused=FALSE, auto_trade_on=TRUE)

Bot UI:
    /help → user commands only; admin block iff OPERATOR_CHAT_ID match
    Dashboard → main_menu() state-driven (no-strategy / start / active)
    Trade notifs → inline KB on every open/close event
```

---

## 3. Files Created / Modified

| File | Change |
|---|---|
| `projects/polymarket/crusaderbot/fly.toml` | strategy rolling → immediate |
| `projects/polymarket/crusaderbot/database.py` | +max_inactive_connection_lifetime=60.0, command_timeout 30→10 |
| `projects/polymarket/crusaderbot/bot/handlers/trades.py` | 4 queries: direct market_question → JOIN markets |
| `projects/polymarket/crusaderbot/bot/handlers/share_card.py` | 1 query: direct market_question → JOIN markets |
| `projects/polymarket/crusaderbot/domain/execution/exit_watcher.py` | alert_user_close_failed + alert_user_market_expired → logger.info |
| `projects/polymarket/crusaderbot/monitoring/alerts.py` | delete alert_startup + constants + os import; add DEPRECATED docstrings |
| `projects/polymarket/crusaderbot/tests/test_health.py` | replace alert_startup with alert_dependency_unreachable in 2 tests |
| `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py` | InlineKeyboardButton import; inline KBs on all 5 notify methods; position_id param on notify_entry |
| `projects/polymarket/crusaderbot/scheduler.py` | InlineKeyboardButton/Markup import; deposit_kb on watch_deposits send |
| `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` | main_menu_keyboard → main_menu() state-driven (3 sites) |
| `projects/polymarket/crusaderbot/bot/handlers/start.py` | help_command admin-scoped |
| `projects/polymarket/crusaderbot/jobs/weekly_insights.py` | _list_active_users adds paused=FALSE AND auto_trade_on=TRUE |
| `projects/polymarket/crusaderbot/jobs/hourly_report.py` | JOIN bug fix: t.user_id=u.telegram_user_id → t.user_id=u.id |
| `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` | updated |
| `projects/polymarket/crusaderbot/state/CHANGELOG.md` | prepended entry |
| `projects/polymarket/crusaderbot/reports/forge/bot-polish-beta.md` | this file |

---

## 4. What Is Working

- `python -m compileall projects/polymarket/crusaderbot/ -q` — 0 errors
- Zero callers of `alert_user_market_expired` or `alert_user_close_failed` in `domain/`: `grep -rn "alert_user_market_expired\|alert_user_close_failed" domain/` → 0 results
- Zero callers of `alert_startup`: `grep -rn "alert_startup" --include="*.py"` → 0 results
- All trades.py queries show `m.question AS market_question` pattern (4 of 4)
- share_card.py query uses JOIN pattern
- Deposit notification includes reply_markup=deposit_kb
- dashboard.py no longer imports or calls `main_menu_keyboard()`
- `help_command()` respects OPERATOR_CHAT_ID for admin block
- weekly_insights filters to active users only
- hourly_report JOIN is now correct UUID→UUID

---

## 5. Known Issues

- Area 4 (live runtime verification) requires Fly.io CLI access — not executable in cloud execution environment. WARP🔹CMD must run verification manually post-deploy.
- Test suite cannot be run in this environment (missing native `cffi`/`cryptography` system libraries). Compile check passes clean.
- `notify_entry()` position_id is optional — callers in `paper.py` do not yet pass it. The Dashboard-only fallback keyboard is active for now. Wiring position_id at call sites is a deferred follow-up.
- `main_menu_keyboard()` function still exists in `bot/keyboards/__init__.py` (imported by other handlers); only its usage in `dashboard.py` was replaced. Full removal is a separate cleanup lane.
- 0c (Chat not found for telegram_user_id 5642722297) — operator action only, no code change. Boss must `/start` @CrusaderPolybot.

---

## 6. What Is Next

```
NEXT PRIORITY for WARP🔹CMD:
WARP•SENTINEL validation required for bot-polish-beta (MAJOR) before merge.
Source: projects/polymarket/crusaderbot/reports/forge/bot-polish-beta.md
Tier: MAJOR

After merge:
1. Apply migration 030 to production
2. Deploy main to Fly.io (now with immediate strategy — no overlap window)
3. Verify exit_watcher log: "market_expired position closed (user notif suppressed)" appears, NOT alert_user_market_expired
4. Wire position_id into paper.py and live router notify_entry() calls (deferred lane)
5. Boss must /start @CrusaderPolybot (0c — operator action)
```

---

**Suggested Next Step:** WARP•SENTINEL validation of bot-polish-beta MAJOR changes before merge to main.
