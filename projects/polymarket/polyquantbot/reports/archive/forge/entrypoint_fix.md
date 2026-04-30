# FORGE-X REPORT — Entrypoint Fix
**Date:** 2026-04-02
**Branch:** claude/fix-entrypoint-runtime-03dFN
**Role:** FORGE-X

---

## 1. ALL ENTRYPOINTS FOUND

| File | Type | Starts Engine | Starts Telegram |
|------|------|--------------|----------------|
| `/home/user/walker-ai-team/main.py` | Root launcher (Procfile) | Delegates to polyquantbot/main.py | Via delegation |
| `projects/polymarket/polyquantbot/main.py` | Core async entrypoint | YES | YES — TelegramLive + polling loop |

**`if __name__ == "__main__"` blocks found:**
- `projects/polymarket/polyquantbot/main.py` line 424 — the ONLY valid block

**Other Telegram-related files (NOT entrypoints):**
- `telegram/telegram_live.py` — alert dispatcher (class, not entrypoint)
- `telegram/command_handler.py` — command dispatch (class, not entrypoint)
- `telegram/command_router.py` — routing (class, not entrypoint)
- `telegram/message_formatter.py` — formatting (module, not entrypoint)
- `api/telegram/menu_handler.py` — NEW menu builder (functions, not entrypoint)
- `api/telegram/menu_router.py` — NEW menu router (class, not entrypoint)
- `api/telegram_webhook.py` — webhook server (class, not entrypoint)

---

## 2. ROOT CAUSE OF BUG

**File:** `telegram/command_handler.py`
**Method:** `_dispatch()`
**Commands:** `start`, `help`, `menu`

The `/start` command was returning a **hardcoded legacy keyboard** with:
- `📋 Markets` → `markets`
- `🔍 Rediscover` → `rediscover`
- `🔢 Set Markets` → `set_markets_prompt`
- `💧 Set Liquidity` → `set_liquidity_prompt`

This was the OLD menu design. The new system (`api/telegram/menu_handler.py`) defines `build_main_menu()` with:
- `📊 Status`, `💰 Wallet`, `⚙️ Settings`, `▶ Control`

---

## 3. CHANGES MADE

### `telegram/command_handler.py`

**Replaced:** Hardcoded legacy keyboard in `start/help/menu` dispatch (lines 221–253)
**With:** `build_main_menu()` from `api/telegram/menu_handler.py`

**Added new callback handlers in `_dispatch()`:**
- `main_menu` → redirects to start/new main menu
- `wallet` → `_handle_wallet()` with `build_wallet_menu()` keyboard
- `wallet_balance`, `wallet_exposure` → stub with /health redirect
- `control` → `_handle_control()` with `build_control_menu()` keyboard
- `control_pause` → aliases `_handle_pause()`
- `control_resume` → aliases `_handle_resume()`
- `control_stop_confirm` → confirmation dialog with `build_stop_confirm_menu()`
- `control_stop_execute` → aliases `_handle_kill()`
- `noop` → silent no-op
- `settings_risk` → prompt message
- `settings_mode` → mode switch dialog with `build_mode_confirm_menu()`
- `mode_confirm_*` → `_handle_mode_confirm_switch()` with ENABLE_LIVE_TRADING guard
- `settings_strategy` → aliases `_handle_strategies()`
- `settings_notify`, `settings_auto` → stub settings responses

**Added new handler methods:**
- `_handle_wallet()` — wallet overview + wallet menu keyboard
- `_handle_control()` — control panel + state-aware control keyboard
- `_handle_mode_confirm_switch()` — mode switch with ENABLE_LIVE_TRADING guard

### `projects/polymarket/polyquantbot/main.py`

**Added startup assertions** at top of `main()`:
```
print("🚀 NEW TELEGRAM SYSTEM ACTIVE")
print("ENTRYPOINT: main.py")
log.info("entrypoint_active", entrypoint="...", system="NEW_TELEGRAM_SYSTEM", status="ACTIVE", legacy_menu="DISABLED")
```

---

## 4. FINAL EXECUTION FLOW

```
Railway deploy
  └─ Procfile: python main.py  (root)
       └─ projects.polymarket.polyquantbot.main.run()
            └─ asyncio.run(main())
                 ├─ [LOG] 🚀 NEW TELEGRAM SYSTEM ACTIVE
                 ├─ [LOG] ENTRYPOINT: main.py
                 ├─ LiveConfig.from_env()
                 ├─ SystemStateManager, ConfigManager, RiskGuard, FillTracker
                 ├─ MetricsExporter.start_logging_loop()
                 ├─ TelegramLive.from_env().start()
                 ├─ SystemActivationMonitor.start()
                 ├─ PolymarketWSClient (if MARKET_IDS set)
                 ├─ CommandHandler (NEW — uses build_main_menu on /start)
                 ├─ DashboardServer (if DASHBOARD_ENABLED=true)
                 ├─ MetricsServer (/health + /metrics)
                 ├─ _heartbeat_loop task
                 ├─ _polling_loop task (Telegram getUpdates)
                 │    └─ CommandRouter → CommandHandler._dispatch()
                 │         ├─ /start → build_main_menu() [NEW DESIGN]
                 │         ├─ /status, /pause, /resume, /kill → handlers
                 │         ├─ wallet, control → NEW handlers
                 │         └─ NO legacy Markets/Rediscover menu
                 └─ run_bootstrap() → LivePaperRunner.run()
```

---

## 5. VALIDATION RESULT

| Check | Result |
|-------|--------|
| Single entrypoint | PASS — only `main.py` |
| New Telegram menu on `/start` | PASS — `build_main_menu()` used |
| Legacy Markets/Rediscover menu | DISABLED — removed from dispatch |
| Startup log assertion | PASS — logs on every boot |
| Entrypoint log assertion | PASS — `entrypoint_active` event |
| New menu callbacks routed | PASS — all callbacks handled |
| ENABLE_LIVE_TRADING guard | PASS — mode switch blocked if not set |
| Procfile command | PASS — `python main.py` → correct path |

**Expected Railway log on startup:**
```
🚀 PolyQuantBot starting (Railway)
🚀 NEW TELEGRAM SYSTEM ACTIVE
ENTRYPOINT: main.py
```

**Expected Telegram `/start` output:**
```
KrusaderBot — Polymarket AI Trader
Mode: PAPER | State: RUNNING

[📊 Status]   [💰 Wallet  ]
[⚙️ Settings] [▶ Control  ]
```

---

## 6. REMAINING RISKS

1. **`api/telegram/menu_router.py`** — requires `WalletManager` not wired in `main.py`. `MenuRouter` is NOT called by the polling loop, so this is safe. Direct wallet balance/exposure shows a placeholder redirecting to `/health`.

2. **`api/telegram_webhook.py`** — webhook server class exists but is NOT started in `main.py`. Railway uses polling (getUpdates), not webhooks. No risk.

3. **Legacy `markets` / `rediscover` commands** — still functional via `/markets` and `/rediscover` text commands (existing handlers in `_dispatch`). They are NOT shown in the menu, so accidental use is unlikely. These can be removed in a future cleanup phase.

4. **WalletManager integration** — wallet menu shows placeholder. Full balance/exposure data requires `WalletManager` to be wired in `main.py` (future phase).

---

**Status: COMPLETE**
