# WARP•FORGE REPORT — telegram-paper-autotrade-readiness

Validation Tier: STANDARD
Claim Level: NARROW INTEGRATION
Validation Target: Telegram inline keyboard regression (UX Overhaul menu drift) + paper autotrade path smoke
Not in Scope: Live trading guard changes, activation guard mutations, capital/risk constants, referral/fee activation
Suggested Next Step: WARP🔹CMD review required. Source: projects/polymarket/crusaderbot/reports/forge/telegram-paper-autotrade-readiness.md. Tier: STANDARD.

---

## 1. What Was Built

### Root Cause — Inline Button Regression

The UX Overhaul (PR #989) replaced the reply keyboard's bottom row from `💰 Wallet` + `🚨 Emergency` to `⚙️ Settings` + `🛑 Stop Bot`. Two ConversationHandlers were not updated to match.

Both `copy_trade.py` and `presets.py` register a fallback `MessageHandler` that intercepts reply-keyboard button taps while a wizard is open. The fallback set and the filter regex were still checking for the old button labels. When a user inside either wizard tapped `⚙️ Settings` or `🛑 Stop Bot`, the wizard's `wizard_fallback_text` handler consumed the message and replied "Tap a button or /menu to exit." — the intended surface never rendered and its inline buttons never appeared.

### Root Cause — Health Job Count Drift

`bot/handlers/health.py` hardcoded `total_jobs_distinct: 11`. The scheduler now registers 17 jobs (6 added since signal-scan-engine PR #991: `market_signal_scanner`, `hourly_report`, `weekly_insights`, `daily_pnl_summary`, `auto_fallback`, `check_resolutions`). The `/health` display was showing `X/11` where 11 is stale.

### Fixes Applied

**Fix 1 — `bot/handlers/copy_trade.py`**
- `_MENU_BUTTONS` (line 711): replaced `"💰 Wallet"` and `"🚨 Emergency"` with `"⚙️ Settings"` and `"🛑 Stop Bot"`
- `build_wizard_handler` fallback regex (line 1796): `r"^(📊|🐋|🤖|📈|💰|🚨)"` → `r"^(📊|🐋|🤖|📈|⚙️|🛑)"`

**Fix 2 — `bot/handlers/presets.py`**
- `_MENU_BUTTONS_CUSTOMIZE` (line 394): same replacement — `💰 Wallet` and `🚨 Emergency` → `⚙️ Settings` and `🛑 Stop Bot`
- `build_customize_handler` fallback regex (line 950): same regex update as above

**Fix 3 — `bot/handlers/health.py`**
- `total_jobs_distinct` (line 93): `11` → `17` to match actual scheduler registrations

---

## 2. Current System Architecture

```
Telegram User
    │
    ▼
bot/dispatcher.py  ──── ConversationHandlers (onboard, copy_trade_wizard, customize_wizard)
    │                          │ fallbacks: _MENU_BUTTONS + Regex (now patched)
    ├── CallbackQueryHandlers (dashboard:, preset:, settings:, insights:, chart:,
    │                          signals:, copytrade:, mytrades:, emergency:, ...)
    └── MessageHandler (text router → MAIN_MENU_ROUTES)

Paper Autotrade Path:
    scheduler.py
        └── signal_following_scan (3 min) ──→ signal_scan_job.run_once()
                └── _load_enrolled_users() (access_tier >= 3, auto_trade_on)
                └── strategy.scan() → SignalCandidate[]
                └── _process_candidate()
                        └── TradeEngine.execute() (13-step risk gate)
                                └── router.execute(chosen_mode=paper)
                                        └── paper.execute()
                                                └── INSERT orders + positions
                                                └── ledger.debit_in_conn()
                                                └── TradeNotifier.notify_entry()
                                                └── audit.write(paper_open)
```

---

## 3. Files Created / Modified

| File | Change |
|---|---|
| `projects/polymarket/crusaderbot/bot/handlers/copy_trade.py` | `_MENU_BUTTONS` + fallback regex updated |
| `projects/polymarket/crusaderbot/bot/handlers/presets.py` | `_MENU_BUTTONS_CUSTOMIZE` + fallback regex updated |
| `projects/polymarket/crusaderbot/bot/handlers/health.py` | `total_jobs_distinct` 11 → 17 |
| `projects/polymarket/crusaderbot/reports/forge/telegram-paper-autotrade-readiness.md` | This report |
| `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` | Updated |
| `projects/polymarket/crusaderbot/state/WORKTODO.md` | No active task items to tick |
| `projects/polymarket/crusaderbot/state/CHANGELOG.md` | Lane closure appended |

---

## 4. What Is Working

### Inline Keyboard — After Fix

All six current menu buttons now correctly exit both wizards:
- `📊 Dashboard` ✅ (was already in old set)
- `📈 My Trades` ✅ (was already in old set)
- `🤖 Auto-Trade` ✅ (was already in old set)
- `🐋 Copy Trade` ✅ (was already in old set)
- `⚙️ Settings` ✅ (fixed — was `💰 Wallet`)
- `🛑 Stop Bot` ✅ (fixed — was `🚨 Emergency`)

Both fallback regex patterns now match all six emoji prefixes.

### Callback Surface Audit (code inspection)

| Surface | Callback prefix | Registered handler | Status |
|---|---|---|---|
| Dashboard nav | `dashboard:` | `dashboard.dashboard_nav_cb` | ✅ |
| Auto-Trade setup | `setup:`, `strategy:`, `set_strategy:`, `set_risk:`, `set_cat:`, `set_mode:`, `set_redeem:` | `setup.*` | ✅ |
| Presets | `preset:` | `presets.preset_callback` | ✅ |
| Preset customize wizard | `customize:*` | `presets.build_customize_handler()` | ✅ |
| Insights | `insights:` | `pnl_insights_h.insights_cb` | ✅ |
| Chart | `chart:` | `portfolio_chart_h.chart_callback` | ✅ |
| My Trades | `mytrades:close_ask:`, `mytrades:close_(yes|no):`, `mytrades:hist:`, `mytrades:back` | `my_trades_h.*` | ✅ |
| Settings | `settings:`, `tp_set:`, `sl_set:`, `cap_set:` | `settings_handler.*` | ✅ |
| Copy Trade | `copytrade:` | `copy_trade.copy_trade_callback` | ✅ |
| Copy Trade wizard | `wizard:*` | `copy_trade.build_wizard_handler()` | ✅ |
| Signal Following | `signals:` | `signal_following.signals_callback` | ✅ |
| Emergency | `emergency:` | `emergency.emergency_callback` | ✅ |
| Onboarding | `onboard:*` | `onboarding.build_onboard_handler()` / `onboarding.view_dashboard_cb` | ✅ |
| Live Gate | `live_gate:` | `live_gate.live_gate_callback` | ✅ |
| Position close | `position:close:`, `position:fc_ask:`, `position:fc_(yes|no):` | `dashboard.*`, `positions.*` | ✅ |
| Autotrade toggle | `autotrade:` | `dashboard.autotrade_toggle_cb` | ✅ |
| Wallet | `wallet:` | `wallet.wallet_callback` | ✅ |
| Admin | `admin:`, `ops:` | `admin.*` | ✅ |
| Market card | `market:` | `market_card.market_callback` | ✅ |
| Referral share | `referral:share:` | `share_card.referral_callback` | ✅ |

No missing or unregistered callback patterns found.

### Paper Autotrade Path — Smoke (code inspection)

Full pipeline verified by code inspection (live DB not reachable in this session):

1. **Signal publication**: `jobs/market_signal_scanner.py` — writes YES/NO edge signals to `signal_publications` (is_demo=TRUE, linked to `DEMO_FEED_ID`)
2. **Signal scan**: `services/signal_scan/signal_scan_job.run_once()` — loads users with `access_tier >= 3`, `auto_trade_on=TRUE`, `paused=FALSE`, enrolled in `user_strategies.signal_following`
3. **Risk gate**: `TradeEngine.execute()` — 13-step gate including Kelly sizing (`a=0.25`), position limits, daily loss cap, kill switch check
4. **Paper execution**: `domain/execution/paper.execute()` — atomic DB transaction: `INSERT INTO orders` (mode=paper, status=filled) + `INSERT INTO positions` (mode=paper, status=open) + `ledger.debit_in_conn()`
5. **User notification**: `TradeNotifier.notify_entry()` via `services/trade_notifications/notifier.py` — sends Telegram entry notification with market, side, size, price, TP/SL
6. **Audit trail**: `audit.write(paper_open)` — persists actor_role=bot, action=paper_open with full payload
7. **Execution queue**: `_insert_execution_queue()` + `_mark_executed()` — permanent dedup anchor prevents re-execution on next tick
8. **Close path**: `paper.close_position()` — updates position status, credits ledger, audit.write(paper_close)

All guards remain OFF: `ENABLE_LIVE_TRADING=false`, `EXECUTION_PATH_VALIDATED=false`, `CAPITAL_MODE_CONFIRMED=false`, `RISK_CONTROLS_VALIDATED=false`, `USE_REAL_CLOB` not set.

---

## 5. Known Issues

- `check_alchemy_ws` is TCP-only (pre-existing, low priority, per PROJECT_STATE)
- `ENABLE_LIVE_TRADING` code default in `config.py` is True but overridden by fly.toml; alignment deferred to WARP/config-guard-default-alignment (pre-existing)
- `domain/execution/live.py` has 4 position UPDATEs missing `AND user_id=$N`; deferred to WARP/live-execution-user-id-guards (pre-existing, not in scope)

---

## 6. What Is Next

- WARP🔹CMD review and merge decision
- Paper-mode closed beta observation continues
- No live activation until explicit owner decision and WARP/live-execution-user-id-guards is merged
