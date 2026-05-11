# WARP•FORGE Report — crusaderbot-fast-trade-notifications

**Branch:** WARP/crusaderbot-fast-trade-notifications-v2
**Date:** 2026-05-11
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Trade notification delivery for paper-mode lifecycle events — ENTRY, TP_HIT, SL_HIT, MANUAL, EMERGENCY, COPY_TRADE scaffold
**Not in Scope:** Live trading alerts, push/email notifications, analytics UI, copy-trade execution logic (Track B), Track D risk caps
**Suggested Next Step:** WARP🔹CMD review; merge when satisfied. Track D (Risk caps + kill switch) is next.

---

## 1. What Was Built

Fast Track C — trade notification service layer for CrusaderBot paper-mode trade lifecycle.

**`services/trade_notifications/notifier.py`** — `TradeNotifier` class

- `NotificationEvent` (str enum): canonical event types — ENTRY, TP_HIT, SL_HIT, MANUAL, EMERGENCY, COPY_TRADE
- `notify_entry()` — compact ENTRY message with side icon, size, price, TP%, SL%, mode, optional strategy label
- `notify_tp_hit()` — TP_HIT close notification with exit price and P&L
- `notify_sl_hit()` — SL_HIT close notification with exit price and P&L
- `notify_manual_close()` — MANUAL close notification after user-initiated close
- `notify_emergency_close()` — EMERGENCY (force-close) notification
- `notify_copy_trade_entry()` — COPY_TRADE scaffold with target wallet truncation (6+4 chars)
- `_send()` — failure-safe internal dispatcher: catches ALL send exceptions, logs at ERROR, never re-raises
- Market question truncated to 60 chars for message compactness; falls back to market_id

**`services/trade_notifications/__init__.py`** — public API re-export

**`domain/execution/paper.py`** (modified)

- Replaced inline `notifications.send()` ENTRY text with `TradeNotifier.notify_entry()` call
- ENTRY notification now includes TP%, SL%, strategy_type, and mode tag
- `_notifier = TradeNotifier()` module-level singleton (stateless, safe to share)

**`monitoring/alerts.py`** (modified)

- Added `alert_user_manual_close()` — user-facing MANUAL close alert, matches existing style of TP/SL/force-close alert functions
- Sends directly to `telegram_user_id` (not operator chat), consistent with exit-watcher user alerts

**`bot/handlers/my_trades.py`** (modified)

- Imported `monitoring.alerts`
- Added `alert_user_manual_close()` call after successful paper close in `close_confirm_cb()`
- Guard: notification fires only when `exit_reason != 'already_closed'` (P2 fix)
- Failure caught with `try/except` + `logger.error()` — UX flow never interrupted by Telegram failure

**`tests/test_trade_notifications.py`** — 16 hermetic tests (all passing)

---

## 2. Current System Architecture

```
Telegram UX (Phase 5A–5I)
        │
        ├── My Trades close_confirm_cb()
        │     → paper.close_position()
        │     → monitoring.alerts.alert_user_manual_close()   ← NEW MANUAL hook
        │
        └── (emergency sets force_close_intent → exit_watcher)

services/signal_scan/signal_scan_job.py   ← active scan loop
  _process_candidate()
    → _engine.execute(signal)
        │
        ▼
services/trade_engine/engine.py
  TradeEngine.execute()
    → risk gate → router.execute()
        │
        ▼
domain/execution/paper.py
  paper.execute()
    → DB INSERT (order + position + ledger debit)
    → TradeNotifier.notify_entry()                            ← ENHANCED ENTRY
        │
        ▼
services/trade_notifications/notifier.py  ← NEW
  TradeNotifier._send()
    → notifications.send() [with failure-safe catch]

domain/execution/exit_watcher.py
  _act_on_decision()
    → monitoring.alerts.alert_user_tp_hit / sl_hit / force_close   ← existing
    (EMERGENCY = FORCE_CLOSE reason, already wired)
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/services/trade_notifications/__init__.py`
- `projects/polymarket/crusaderbot/services/trade_notifications/notifier.py`
- `projects/polymarket/crusaderbot/tests/test_trade_notifications.py`
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-fast-trade-notifications.md`

**Modified:**
- `projects/polymarket/crusaderbot/domain/execution/paper.py` — TradeNotifier wired for ENTRY; removed raw notifications.send() call
- `projects/polymarket/crusaderbot/monitoring/alerts.py` — added `alert_user_manual_close()`
- `projects/polymarket/crusaderbot/bot/handlers/my_trades.py` — added MANUAL notification hook in close_confirm_cb; already_closed guard (P2 fix)

---

## 4. What Is Working

- 16/16 hermetic tests pass locally
- All 6 notification event types implemented (ENTRY, TP_HIT, SL_HIT, MANUAL, EMERGENCY, COPY_TRADE scaffold)
- Failure-safe contract enforced: `TradeNotifier._send()` catches all exceptions, logs at ERROR, never re-raises
- ENTRY notification enhanced: side icon, size, price, TP%, SL%, mode tag, strategy label
- MANUAL close notification wired in `my_trades.close_confirm_cb()` with its own try/except guard
- TP_HIT, SL_HIT, FORCE_CLOSE (EMERGENCY) already wired through exit_watcher → monitoring.alerts; not duplicated
- COPY_TRADE scaffold ready for Track D/E wiring (target_wallet param accepted)
- No activation guard mutations — paper mode only
- No threading — asyncio throughout
- Full type hints on all production code
- No `phase*/` folders
- Branch rebased cleanly onto main post-Track-B merge

---

## 5. Known Issues

- COPY_TRADE `notify_copy_trade_entry()` is a scaffold: it exists in `TradeNotifier` but is not wired into any execution path yet. Copy Trade monitor (Track B) can call it when copy_trade positions open.
- `alert_user_manual_close()` uses the existing `alerts.py` plain-markdown format (`$+7.50`) rather than the `TradeNotifier` `+$7.50` format. The formats are consistent with the rest of `monitoring/alerts.py` (intentional).
- The `_notifier` singleton in `paper.py` is at module level. It is stateless and safe to share; no threading issues.

---

## 6. What Is Next

- WARP🔹CMD review and merge decision (STANDARD tier — no SENTINEL required)
- Track D (Risk caps + kill switch hardening) — MAJOR, SENTINEL REQUIRED
- Track E (Daily P&L report) — STANDARD, can proceed after Track D
