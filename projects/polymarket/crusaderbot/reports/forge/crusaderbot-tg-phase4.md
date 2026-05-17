# WARP•FORGE REPORT — crusaderbot-tg-phase4

**Branch:** claude/crusaderbot-telegram-phase4-A9FvW
**Linear:** CRU-15
**Date:** 2026-05-17
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION

---

## 1. What Was Built

Telegram Power Mode Phase 4 — three feature areas:

**A. Push Notifications (3 event types)**
- Auto Trade Executed: fires on successful `position.opened` event (non-copy-trade fills). Format: `🚨 Auto Trade Executed / Bought $X SIDE / Market: … / Price: … | Strategy: …`
- Copy Trade Triggered: fires on `copy_trade.executed` event. Format: `👥 Copy Trade Triggered / Copied: wallet / Bought $X SIDE | Market: …`
- Trade Blocked: fires when risk gate rejects with `insufficient_liquidity` or `market_impact_cap`. 5-minute anti-spam cooldown per user. Format: `⚠️ Trade Blocked / Market: … / Reason: …`

**B. Quick Action Inline Buttons**
- Auto Trade notification: `[📊 View Position] [❌ Close Position] [🌐 Dashboard]`
- Copy Trade notification: `[📊 View Position] [⏸ Pause Copy] [🌐 Dashboard]`
- View Position → reuses `mytrades:open:{position_id}` (existing trade_detail_cb)
- Close Position → reuses `close_position:{position_id}` confirmation flow (existing close_ask_cb/close_confirm_cb)
- Pause Copy → `tgnotif:pause_copy:{copy_task_id}` sets copy_trade_task status='paused'
- Dashboard → `tgnotif:dashboard` sends WEBTRADER_URL from config

**C. Emergency Controls Extension**
- /emergency menu now shows 4 new buttons in top row before existing controls
- Stop All Auto Trade: sets `auto_trade_on=False`, audit logged
- Kill All Positions: marks all open positions with `force_close_intent=TRUE`, audit logged
- Lock Bot: sets `paused=True + auto_trade_on=False + locked=True`, audit logged
- System Status: read-only snapshot (auto-trade state, lock state, open positions, active copy tasks)
- Auth gate: all actions verify user exists via `get_user_by_telegram_id` before executing; unknown users rejected with `Not authorized.`

---

## 2. Current System Architecture

```
Trade Engine (engine.py)
  ├── Risk gate rejected (insufficient_liquidity | market_impact_cap)
  │     └── event_bus.emit("trade.blocked") → _on_trade_blocked (5-min cooldown)
  └── Approved + non-duplicate + strategy_type != "copy_trade"
        └── event_bus.emit("position.opened") → _on_position_opened
              → Telegram: 🚨 Auto Trade Executed + [View|Close|Dashboard] KB

Copy Trade Monitor (monitor.py)
  └── Approved + non-duplicate
        └── event_bus.emit("copy_trade.executed") → _on_copy_trade_executed
              → Telegram: 👥 Copy Trade Triggered + [View|Pause Copy|Dashboard] KB

tg_power_mode_cb (bot/handlers/tg_power_mode.py)
  ├── tgnotif:pause_copy:{id}  → UPDATE copy_trade_tasks SET status='paused'
  └── tgnotif:dashboard        → send WEBTRADER_URL (config.WEBTRADER_URL)

emergency_callback (bot/handlers/emergency.py)
  ├── p5:emergency:confirm:system_status → _system_status_text() (read-only, no confirm step)
  ├── p5:emergency:ask:stop_auto_trade  → confirm → set_auto_trade(False)
  ├── p5:emergency:ask:kill_all_positions → confirm → mark force_close_intent all positions
  └── p5:emergency:ask:lock_bot         → confirm → paused+auto_trade_off+locked
```

---

## 3. Files Created / Modified

**Created:**
- `projects/polymarket/crusaderbot/bot/handlers/tg_power_mode.py`

**Modified:**
- `projects/polymarket/crusaderbot/config.py` — added `WEBTRADER_URL: Optional[str] = None`
- `projects/polymarket/crusaderbot/services/notification_service.py` — new notification formats, inline keyboards, `_on_trade_blocked` handler, `trade.blocked` subscription, 5-min anti-spam cooldown
- `projects/polymarket/crusaderbot/services/trade_engine/engine.py` — emits `position.opened` (non-copy-trade fills), emits `trade.blocked` (liquidity/slippage rejections); added `_blocked_reason_display()` helper
- `projects/polymarket/crusaderbot/services/copy_trade/monitor.py` — added `market_question`, `price`, `position_id`, `copy_task_id` to `copy_trade.executed` event; fixed field name (`entry_price` → `price` per handler signature)
- `projects/polymarket/crusaderbot/bot/handlers/emergency.py` — added `stop_auto_trade`, `kill_all_positions`, `lock_bot`, `system_status` actions; auth gate via `get_user_by_telegram_id`; added `_system_status_text()` helper
- `projects/polymarket/crusaderbot/bot/messages.py` — new EMERGENCY_CONFIRM_TEXTS entries for 3 new actions; new `emergency_feedback_text` labels; added `emergency_system_status_text()` function
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — extended `emergency_p5_kb()` with 4 new buttons in top rows; System Status uses confirm: directly (no ask step)
- `projects/polymarket/crusaderbot/bot/dispatcher.py` — registered `tg_power_mode_cb` for `^tgnotif:` pattern; imported from `tg_power_mode`
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — updated
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — lane closure appended
- `projects/polymarket/crusaderbot/reports/forge/crusaderbot-tg-phase4.md` — this file

---

## 4. What Is Working

1. `position.opened` event now fired from trade engine for all non-copy, non-duplicate fills
2. `copy_trade.executed` event now carries `position_id`, `copy_task_id`, `market_question`, `price` (fixed field name from `entry_price`)
3. `trade.blocked` event emitted for gate steps 11 (liquidity) and 14 (slippage), with 5-min per-user cooldown preventing spam
4. Auto Trade notification uses concise format with 3-button inline keyboard
5. Copy Trade notification uses concise format with 3-button inline keyboard (Pause Copy wired to task ID)
6. `tgnotif:pause_copy:{copy_task_id}` sets copy_trade_task status='paused'; user-scoped (user_id check in WHERE clause)
7. `tgnotif:dashboard` sends WEBTRADER_URL or "not configured" message
8. `/emergency` menu now shows 4 new controls + existing 3 controls
9. `stop_auto_trade` → `set_auto_trade(user_id, False)` + audit log
10. `kill_all_positions` → marks all open positions force_close_intent=TRUE + audit log
11. `lock_bot` → paused + auto_trade_off + locked + audit log
12. `system_status` → read-only snapshot, bypasses confirm step
13. Auth gate: `get_user_by_telegram_id` check before all emergency actions — unknown users rejected
14. Paper mode guards untouched: `ENABLE_LIVE_TRADING` guard is unchanged; migrations 030-038 not touched

---

## 5. Known Issues

- `WEBTRADER_URL` must be set in environment for Dashboard button to send a real link; defaults to "not configured" message otherwise
- System Status copy task count queries `copy_trade_tasks` table only; legacy `copy_targets` table copy tasks not counted (by design — new wizard uses `copy_trade_tasks`)
- `trade.blocked` cooldown is per-process (module-level dict); resets on process restart; acceptable for paper mode

---

## 6. What Is Next

- WARP🔹CMD review and merge decision
- Set `WEBTRADER_URL=<fly-app-url>` in Fly.io secrets to activate Dashboard button
- Future lane: add `trade.blocked` cooldown to Redis for multi-process durability (WARP🔹CMD decision required)

---

**Validation Target:** Telegram notification pipeline for auto-trade, copy-trade, and risk-blocked events; inline action buttons; /emergency extended controls

**Not in Scope:** Live trading guards, migrations 030-038, WebTrader frontend, signal scanner changes, paper engine changes

**Suggested Next Step:** WARP🔹CMD review of PR. Set `WEBTRADER_URL` in Fly.io secrets post-merge.

---

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
