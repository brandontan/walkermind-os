# WARP-65 Forge Report — Telegram UX Fix

**Branch:** WARP/warp65-telegram-ux-fix
**Issue:** #1278
**Date:** 2026-05-22
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION

---

## 1. What was built

Fixed the MVP Telegram persistent keyboard and bot status display:

**A. `main_menu_kb()` → `ReplyKeyboardMarkup` (blueprint v7 Section 3)**
Replaced the 8-button `InlineKeyboardMarkup` with a 3-row `ReplyKeyboardMarkup` that pins to the bottom of the Telegram screen. Signature gains `auto_on`, `paused`, `open_count` params to reflect live bot state:
- `auto_on=True + paused=False` → "🤖 Auto Mode" label
- `paused=True` → "▶️ Resume" label
- `auto_on=False` → "🤖 Setup Auto" label
- `open_count > 0` → "💼 Trades (N)" label on portfolio button

**B. `_send.py` — ReplyKeyboardMarkup routing**
`ReplyKeyboardMarkup` cannot be passed to `edit_message_text` (Telegram API restriction). Added detection at the top of `send_or_edit`: when keyboard is `ReplyKeyboardMarkup`, always routes through `reply_text` (answers the callback query first if present). All `InlineKeyboardMarkup` paths remain unchanged.

**C. `dashboard.py` — status logic, strategy label, open_count**
- `open_count`: fetched via `_users.fetch_open_position_count` (already existed)
- Bot status: three-state logic — `STATUS_RUNNING` (running), `STATUS_STOPPED` (configured but not running), `STATUS_NOT_SET` (not configured). Previously only two states (running / not_set).
- Strategy label: reads `PRESET_CONFIG.get(preset, {}).get("name")` for human-readable name (e.g., "Whale Mirror", "Crypto Scalper") instead of title-casing the preset key.
- `main_menu_kb()` now called with `auto_on`, `paused`, `open_count` params derived from `_read_dashboard` data.

**D. `autotrade.py:do_start()` — launch keyboard**
After the "Bot Started" confirmation message, sends `main_menu_kb(auto_on=True)` via `reply_text` so the persistent keyboard appears immediately on bot activation.

---

## 2. Current system architecture

MVP Telegram UX layer. Pipeline untouched (RISK → EXECUTION boundary preserved). No DB schema change. No execution path change.

```
User /start or callback
    → show_dashboard()
        → _read_dashboard() [DB: users, settings, balance, pnl, open positions]
        → send_or_edit(update, text, ReplyKeyboardMarkup)
            → reply_text() [keyboard always attaches on new message]
```

---

## 3. Files created / modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/bot/keyboards/mvp/_common.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/mvp/_send.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/mvp/dashboard.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/mvp/autotrade.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/warp65-telegram-ux-fix.md` |

---

## 4. What is working

- `main_menu_kb()` returns `ReplyKeyboardMarkup` with correct labels for all 3 auto states
- `send_or_edit` routes `ReplyKeyboardMarkup` via `reply_text` cleanly — no API type error
- Dashboard: `STATUS_STOPPED` now shown when bot is configured but paused/stopped (previously showed "Not Set")
- Strategy label shows human-readable preset name from `PRESET_CONFIG`
- `open_count` populates portfolio button label
- `do_start()` sends persistent keyboard after activation
- pytest: 1613 passed, 0 failed, 1 skipped
- ruff check: all passed
- py_compile: clean

---

## 5. Known issues

- `do_start()` sends `reply_text(".")` to attach the keyboard — the "." message is visible to users. This is the standard PTB workaround for attaching ReplyKeyboards after a sequence that used `edit_message_text`. A future UX pass could suppress it.
- `send_or_edit` with `ReplyKeyboardMarkup` always sends a new message (does not edit in-place). For callback-triggered dashboard refreshes, this means a new message is sent rather than editing. Acceptable for paper-mode beta; a future lane could suppress duplicate dashboard messages.

---

## 6. What is next

- WARP🔹CMD review and merge
- Fly.io redeploy so running bot pod imports updated handlers
- SENTINEL re-audit (unblocked once CI is green after WARP-64+65)

---

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** MVP Telegram keyboard + dashboard status display
**Not in Scope:** execution path, risk gate, WebTrader, legacy Telegram handlers
**Suggested Next Step:** WARP🔹CMD merge → Fly.io redeploy → SENTINEL re-audit
