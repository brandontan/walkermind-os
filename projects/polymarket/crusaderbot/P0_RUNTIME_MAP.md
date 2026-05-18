# P0 RUNTIME MAP — CrusaderBot
Generated: 2026-05-17 10:48 Asia/Jakarta
Branch: WARP/CRUSADERBOT-MVP-RUNTIME-V1
Phase: Phase 0 — Runtime audit (no code changed)

---

## Entry Point

File: `projects/polymarket/crusaderbot/main.py`
- FastAPI app + lifespan context manager
- Python-telegram-bot Application (webhook or polling)
- APScheduler 12 background jobs
- 3 activation guards validated at boot (ENABLE_LIVE_TRADING, EXECUTION_PATH_VALIDATED, CAPITAL_MODE_CONFIRMED)
- Startup alert to OPERATOR_CHAT_ID with 60s Redis dedup

---

## Handler Classification

Legend: WORKING | BROKEN | FAKE | DEAD | TIER/OPERATOR

### Command Handlers (dispatcher.py:154-191)

| Command | Handler | File | Status |
|---------|---------|------|--------|
| `/start` | `build_start_handler()` | `bot/handlers/start.py` | WORKING — ConversationHandler, 4-step onboarding, paper seed $1000 |
| `/help` | `help_command()` | `bot/handlers/start.py` | WORKING |
| `/menu` | `show_dashboard_for_cb()` | `bot/handlers/dashboard.py` | WORKING |
| `/dashboard` | `dashboard()` | `bot/handlers/dashboard.py` | WORKING |
| `/positions` | `show_positions()` | `bot/handlers/positions.py` | WORKING |
| `/activity` | `activity()` | `bot/handlers/dashboard.py` | WORKING |
| `/settings` | `settings_root()` | `bot/handlers/settings.py` | WORKING |
| `/preset` | `show_autotrade()` | `bot/handlers/autotrade.py` | WORKING |
| `/setup_advanced` | `setup_legacy_root()` | `bot/handlers/setup.py` | WORKING (legacy path) |
| `/emergency` | `emergency_root()` | `bot/handlers/emergency.py` | WORKING |
| `/admin` | `admin_root()` | `bot/handlers/admin.py` | WORKING — gated admin (is_admin check) |
| `/allowlist` | `allowlist_command()` | `bot/handlers/admin.py:341` | TIER/OPERATOR — uses `_is_operator()` not `is_admin()` |
| `/ops_dashboard` | `ops_dashboard_command()` | `bot/handlers/admin.py` | WORKING — admin-gated |
| `/killswitch` | `killswitch_command()` | `bot/handlers/admin.py` | WORKING — admin-gated |
| `/kill` | `kill_command()` | `bot/handlers/admin.py` | WORKING — admin-gated |
| `/resume` | `resume_command()` | `bot/handlers/admin.py` | WORKING — admin-gated |
| `/health` | `health_command()` | `bot/handlers/health.py` | WORKING — admin-gated |
| `/jobs` | `jobs_command()` | `bot/handlers/admin.py` | WORKING — admin-gated |
| `/auditlog` | `auditlog_command()` | `bot/handlers/admin.py` | WORKING — admin-gated |
| `/unlock` | `unlock_command()` | `bot/handlers/admin.py` | WORKING — admin-gated |
| `/resetonboard` | `resetonboard_command()` | `bot/handlers/admin.py` | WORKING — admin-gated |
| `/copytrade` | `copy_trade_command()` | `bot/handlers/copy_trade.py` | WORKING |
| `/signals` | `signals_command()` | `bot/handlers/signal_following.py` | WORKING |
| `/live_checklist` | `live_checklist_command()` | `bot/handlers/activation.py` | WORKING — shows 4-guard status |
| `/enable_live` | `enable_live_command()` | `bot/handlers/live_gate.py` | WORKING — 3-step gate, all 4 guards required |
| `/summary_on` | `summary_on_command()` | `bot/handlers/activation.py` | WORKING |
| `/summary_off` | `summary_off_command()` | `bot/handlers/activation.py` | WORKING |
| `/insights` | `pnl_insights_command()` | `bot/handlers/pnl_insights.py` | WORKING — 3-trade minimum gate |
| `/chart` | `chart_command()` | `bot/handlers/portfolio_chart.py` | WORKING |
| `/market` | `market_command()` | `bot/handlers/market_card.py` | WORKING |
| `/referral` | `referral_command()` | `bot/handlers/referral.py` | WORKING (wiring deferred) |
| `/trades` | `my_trades()` | `bot/handlers/trades.py` | WORKING |
| `/about`, `/status`, `/demo` | `demo_polish.*` | `bot/handlers/demo_polish.py` | WORKING |

### Callback Handler Status

| Pattern | Handler | Status |
|---------|---------|--------|
| `^menu:` | `_menu_nav_cb()` | WORKING — group=-1, fires before ConvHandler |
| `^nav:` | `_nav_cb()` | WORKING — nav:home/back/refresh/noop |
| `^p5:(preset\|confirm\|active):` | `autotrade_callback()` | WORKING |
| `^p5:emergency:` | `emergency_callback()` | WORKING |
| `^close_position:` | `close_ask_cb()` + `close_confirm_cb()` | WORKING |
| `^p5:wallet:` / `^wallet:` | `wallet_callback()` | WORKING |
| `^setup:` | `setup_callback()` | WORKING |
| `^preset:` | `preset_callback()` | WORKING |
| `^set_strategy:` | `set_strategy()` | WORKING |
| `^settings:` | `settings_callback()` | WORKING |
| `^dashboard:` | `dashboard_nav_cb()` | WORKING |
| `^autotrade:` | `autotrade_toggle_cb()` | WORKING |
| `^position:fc_ask:` / `^position:fc_(yes\|no):` | `force_close_*` | WORKING |
| `^insights:` | `insights_cb()` | WORKING |
| `^chart:` | `chart_callback()` | WORKING |
| `^admin:` | `admin_callback()` | WORKING |
| `^ops:` | `ops_dashboard_callback()` | WORKING |
| `^copytrade:` | `copy_trade_callback()` | WORKING |
| `^signals:` | `signals_callback()` | WORKING |
| `^live_gate:` | `live_gate_callback()` | WORKING |
| `^portfolio:` | `portfolio_callback()` | WORKING |
| `^autotrade:\|^p5:preset:` (onboarding) | `preset_selected_in_onboard_cb` | BROKEN — preset saved to user_data only, never applied to DB on skip |

---

## Full Auto-Trade Pipeline Status

```
/start
  → upsert_user (creates user row + enrolls signal_following)   ✅ WORKING
  → paper seed $1,000 USDC on balance=0                         ✅ WORKING
  → preset picker shown                                         ✅ WORKING
  → preset_selected_in_onboard_cb saves preset_key to user_data ⚠️ BROKEN
  → skip_deposit_cb marks onboarding_complete                   ❌ GAP
      ↳ Does NOT apply preset (no update_settings / set_auto_trade call)
      ↳ auto_trade_on remains FALSE after onboarding!

Signal Scanner (scheduler, every 30s)
  → signal_scan_job._load_enrolled_users()                      ✅ WORKING
      ↳ WHERE auto_trade_on=TRUE AND paused=FALSE               ← user not picked up!

Risk Gate (13 steps)                                           ✅ WORKING
Paper Execution (atomic: debit + insert + notify)              ✅ WORKING
Exit Watcher (TP/SL/expiry every 30s)                         ✅ WORKING
Trade Notifications (entry/exit receipts)                      ✅ WORKING
Portfolio (positions, trades, insights)                        ✅ WORKING
Admin panel                                                    ✅ WORKING
```

**CRITICAL BUG:** After onboarding, `auto_trade_on = FALSE`. Scanner ignores user. No trades ever open automatically.
**FIX REQUIRED:** `skip_deposit_cb` in `bot/handlers/start.py` must apply the selected preset (call `_on_activate` logic or inline equivalent) before marking onboarding complete.

---

## Files Requiring Changes

| File | Change | Priority |
|------|--------|----------|
| `bot/handlers/start.py` | Apply preset + set auto_trade_on=True in `skip_deposit_cb` | CRITICAL |
| `bot/handlers/admin.py` | Replace `_is_operator()` with `is_admin()` in `allowlist_command` | HIGH |
| `state/PROJECT_STATE.md` | Resolve merge conflict in [NEXT PRIORITY] section | HIGH |
| `state/CHANGELOG.md` | Append lane closure entry | HIGH |

---

## Tier/Operator References to Purge

| File | Reference | Disposition |
|------|-----------|-------------|
| `bot/tier.py` | `Tier.ALLOWLISTED`, `TIER_MSG`, `has_tier`, `tier_block_message` | KEEP — legacy compat, not user-visible; `tier_gate.py` is no-op |
| `bot/handlers/presets.py:49` | `_ensure_tier2` function name | KEEP — renamed to passthrough already; cosmetic only |
| `bot/handlers/admin.py:42` | `_is_operator()` used in `allowlist_command` | REPLACE with `is_admin()` |
| `bot/middleware/access_tier.py:28` | `TIER_PREMIUM` message | KEEP — only gating admin handler; not user-visible in paper mode |
| `services/allowlist.py` | AllowlistStore | KEEP — backing the `/allowlist` admin command; not user-blocking |
| `bot/dispatcher.py:168` | `CommandHandler("allowlist", ...)` | KEEP — admin-only command; rename to /settier if desired in next lane |

---

## Strategy Status

| Strategy | File | Status |
|----------|------|--------|
| `signal_following` | `services/signal_scan/signal_scan_job.py` | REAL — full execution pipeline |
| `copy_trade` | `domain/signal/copy_trade.py` | REAL |
| `edge_finder` | `jobs/market_signal_scanner.py` | REAL |
| `momentum_reversal` | `jobs/market_signal_scanner.py` | REAL |
| `value` | `domain/signal/value.py` | STUB — returns `[]` |

---

## Scheduler Jobs

| Job | Interval | Status |
|-----|----------|--------|
| market_sync | 60s | REAL |
| watch_deposits | 30s | REAL |
| watch_withdrawals | 30s | REAL |
| market_signal_scanner | 60s | REAL |
| signal_scan_job | 30s | REAL |
| exit_watcher | 30s | REAL |
| copy_trade_monitor | 60s | REAL |
| redeem_hourly_worker | 60s | REAL |
| daily_pnl_summary | 1AM daily | REAL |
| hourly_report | Hourly | REAL |
| weekly_insights | Mon 1AM | REAL |
| auto_fallback_check | 60s | REAL |

---

## Activation Guards (all OFF — do not touch)

```
ENABLE_LIVE_TRADING=false          ← config.py default + fly.toml forced
EXECUTION_PATH_VALIDATED=false     ← config.py default
CAPITAL_MODE_CONFIRMED=false       ← config.py default
RISK_CONTROLS_VALIDATED=false      ← config.py default
```

All 4 are flipable to `true` without new code. Live infrastructure is fully built and gated.

---

## P0 Done Criteria

- [x] P0_RUNTIME_MAP.md exists with full handler classification
- [x] No code changed in Phase 0
- [x] Critical bug identified: auto_trade_on not set in onboarding
- [x] File change list produced
