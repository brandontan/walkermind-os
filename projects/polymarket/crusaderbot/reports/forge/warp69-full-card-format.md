# WARP•FORGE REPORT — warp69-full-card-format

Validation Tier: STANDARD
Claim Level: VISUAL/UX
Validation Target: All 66 render functions in bot/messages_mvp.py use structured card format (leaf · separator, section(), nested(), cta(), DIVIDER, CARD_DIVIDER)
Not in Scope: handlers, keyboards, dispatcher, domain logic, DB queries, scheduler, activation guards
Suggested Next Step: WARP🔹CMD review required.

---

## 1. What Was Built

WARP-69 completes the structured card format rollout across all render functions in `messages_mvp.py`. WARP-68 established the format and updated 2/66 functions (`render_dashboard_default`, `render_positions_list`). This PR updates the remaining 64 functions.

Key structural changes:

- **`render_dashboard_new_user()`** — restructured to match `render_dashboard_default` pattern: raw f-string with `divider()` separator line and `cta()` at end (STATUS_NOT_SET values preserved per issue spec)
- **`render_autotrade_home()`** — DIVIDER inserted between Status/Config/Perf sections; `leaf('Status')` and `leaf('Active Strategy')` on separate lines above first DIVIDER
- **`render_settings_home()`** — values shortened for mobile-safe rendering (no line wrapping): "Daily limits ON", "Trade alerts ON", "Mirroring", "Profile", "Power user"
- **Auto Trade config screens** — `render_autotrade_configure_strategy()` and `render_autotrade_configure_risk()` use `nested()` for option lists; `render_autotrade_configure_review()` uses `section("Your Setup", ...)`
- **Copy Wallet screens** — `render_copy_wallet_review()` and `render_copy_wallet_configure()` use `section()` for grouped info; `render_copy_wallet_card()` uses explicit `CARD_DIVIDER`
- **Markets screens** — `render_markets_home()` uses `section("Browse", ...)`; `render_markets_trending()` uses `CARD_DIVIDER` between each market card; `render_markets_ai_insight()` uses `nested("Analysis", ...)`
- **Portfolio screens** — `render_portfolio_home()` uses DIVIDER between Balance/Today/Positions; `render_position_detail()` uses `CARD_DIVIDER` before section; `render_performance()` and `render_balance()` use `section()`
- **Settings screens** — `render_settings_risk_controls()`, `render_settings_notifications()`, `render_settings_account()`, `render_settings_advanced()` all use `section()`; `render_settings_live_gate()` uses `nested()` for activation requirements; `render_settings_trading_mode()` uses leaf + section
- **Help screens** — `render_help_home()` uses `nested("Topics", ...)` + `cta()`; `render_help_quick_start_guide()` uses `nested("Steps", ...)`; `render_help_safety()` uses two `nested()` blocks (Protections, Warnings)
- **System screens** — `render_loading()` uses `cta(message)`; `render_syncing()` uses `leaf("Status", message)`; `render_welcome()` uses `nested("Get Started", ...)` + `cta()`; `render_wallet_ready()` uses `cta()`
- **Notification screens** — already used `leaf()` throughout; `last=True` flags removed (cosmetic cleanup)
- **All plain string CTAs** — "Choose an action:", "Ready to begin?", "Confirm pause?", etc. converted to `cta(...)` calls across all screens

---

## 2. Current System Architecture

```
bot/messages_mvp.py          ← all 66 render functions (this PR)
bot/ui/tree.py               ← helpers unchanged (WARP-68)
    title()   → *bold*
    leaf()    → Label  ·  Value
    section() → *Header* + indented leaf rows
    nested()  → *Header* + bullet lines
    divider() → ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
    cta()     → _italic CTA_
    DIVIDER   → constant (same as divider())
    CARD_DIVIDER → ━━━━━━━━━━━━━━━━
    join_blocks() → title \n\n block \n block ...
```

Format pattern in use:
- Screen title: `title("🤖 Auto Trade")` → `*🤖 Auto Trade*`
- Key-value row: `leaf("Status", status)` → `Status  ·  🔴 Stopped`
- Grouped rows: `section("⚙️ Config", [("Capital", "$100"), ...])` → bold header + indented rows
- Bullet list: `nested("Topics", ["step 1", ...])` → bold header + `• item` lines
- Section break: `divider()` or `DIVIDER` → `┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄`
- Card break: `CARD_DIVIDER` → `━━━━━━━━━━━━━━━━`
- CTA: `cta("Choose an action:")` → `_Choose an action:_`

---

## 3. Files Created / Modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/bot/messages_mvp.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/warp69-full-card-format.md` |
| Updated  | `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` |
| Updated  | `projects/polymarket/crusaderbot/state/WORKTODO.md` |
| Updated  | `projects/polymarket/crusaderbot/state/CHANGELOG.md` |

---

## 4. What Is Working

- All 66 render functions produce structured card format output
- `py_compile` clean on `bot/messages_mvp.py`
- `render_dashboard_default` and `render_positions_list` unchanged from WARP-68
- `render_settings_home()` values shortened — no value exceeds ~20 chars (mobile-safe)
- `render_dashboard_new_user()` matches issue-specified exact format with divider + STATUS_NOT_SET rows + cta
- `render_autotrade_home()` has clear DIVIDER between Status, Config, and Performance blocks
- All plain-string CTAs replaced with `cta()` — italic rendering on Telegram
- CARD_DIVIDER used in: `render_positions_list`, `render_copy_wallet_card`, `render_markets_trending`, `render_position_detail`
- `nested()` used in: `render_autotrade_configure_strategy`, `render_autotrade_configure_risk`, `render_settings_live_gate`, `render_help_home`, `render_help_quick_start_guide`, `render_help_safety`, `render_welcome`, `render_markets_ai_insight`, `render_help_how_auto_trade`, `render_help_how_copy_wallet`
- No imports changed — all helpers already available from WARP-68

---

## 5. Known Issues

None. All changes are pure formatting in isolated renderer functions.

---

## 6. What Is Next

- WARP🔹CMD review + merge decision
- Post-merge: Fly.io redeploy required so the running bot pod imports the updated renderers
- On-device render check (Android Telegram + iOS Telegram) to verify `·` separator, `┄` dividers, `━` card dividers, and italic CTAs render as expected
- No migration required
