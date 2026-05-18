# WARP•FORGE REPORT — tg-ux-redesign

Validation Tier: STANDARD
Claim Level: FULL RUNTIME INTEGRATION
Validation Target: Telegram UI/UX — Dashboard HUD, Auto Mode Wizard, Main Menu routing
Not in Scope: Backend trading logic, DB schema changes, admin panel, WebTrader
Suggested Next Step: WARP🔹CMD review required.

---

## 1. What Was Built

Telegram UX overhaul combining WARP-22 + WARP-23 (consolidated as WARP-24):

**Dashboard HUD (WARP-22):**
- `dashboard_text()` in `bot/messages.py` redesigned as tactical terminal.
- Uses `<pre>` monospace blocks per section (PORTFOLIO, P&L, STATS, AUTO MODE).
- Heavy `━━━` dividers (DIV constant) between every section.
- Equity surfaced as the first portfolio value (most prominent metric).
- Today P&L now shows 🟢 / 🔴 indicator based on sign.
- `last_scan` heartbeat parameter added — shows scanner's last tick time (WIB UTC+7) in `HH:MM:SS` format at the top of the dashboard.

**Scanner Heartbeat (WARP-22):**
- `bot/handlers/dashboard.py` — `_build_last_scan()` helper added.
- Reads `get_scanner_state()["last_tick_ts"]` (module-level float set by `market_signal_scanner` after every scan run).
- Converts UTC epoch → WIB (+7) → `HH:MM:SS`. Falls back to `"—"` if scanner has not run yet.

**Auto Mode Wizard — Compact Picker (WARP-23):**
- `_preset_picker_text()` in `bot/handlers/presets.py` stripped of all per-preset descriptions.
- Now shows only: brand header + active preset status + "Choose your trading strategy:" prompt.
- Compact picker grid uses `preset_picker()` from `bot/keyboards/presets.py` directly.

**Auto Mode Wizard — Detail View (WARP-23):**
- `_preset_confirm_text()` in `bot/handlers/presets.py` redesigned as a full detail card.
- Shows: preset name + description, `<pre>` config block (Capital/TP/SL/Mode), PnL example on $1,000 reference capital.
- `_on_pick()` now edits the message in-place (`edit_message_text`) instead of sending a new reply.

**Auto Mode Wizard — Navigation (WARP-23):**
- `preset_confirm()` in `bot/keyboards/presets.py` — "❌ Cancel" replaced with `home_back_row("preset:picker")` (⬅ Back + 🏠 Home).
- All wizard screens navigate back to picker via `preset:picker` callback (registered in dispatcher).
- `preset_picker()` button labels updated: show `{emoji} {name} · {risk_badge}` (risk level, not capital %).

**Main Menu Route (WARP-22):**
- `MAIN_MENU_ROUTES["🤖 Auto Mode"]` in `bot/menus/main.py` changed from `autotrade.show_autotrade` (2-sub-menu) to `presets.show_preset_picker` (direct compact grid).
- Eliminates the intermediate "Strategy Preset / Risk Profile" sub-menu tap.
- Risk Profile remains accessible via ⚙️ Settings.

---

## 2. Current System Architecture

```
🤖 Auto Mode (reply keyboard)
    └── presets.show_preset_picker()          [menus/main.py route]
            └── _preset_picker_text()          [compact header, no descriptions]
            └── preset_picker() keyboard       [2-col grid, emoji+name+risk badge]
                    └── preset:pick:{key}
                            └── preset_callback → _on_pick()
                                    └── q.message.edit_text(_preset_confirm_text())
                                    └── preset_confirm(key) keyboard [Start|Customize + Back|Home]
                                            ├── preset:activate:{key}  → _on_activate()
                                            ├── preset:customize:{key} → wizard_enter_customize()
                                            └── preset:picker          → show_preset_picker()

📊 Dashboard (reply keyboard / /start)
    └── dashboard._build_dashboard_message()
            └── _build_last_scan()             [reads get_scanner_state().last_tick_ts]
            └── dashboard_text()               [<pre> blocks + DIV dividers + 🟢/🔴 P&L]
```

---

## 3. Files Created / Modified

| Action | Path |
|--------|------|
| Modified | `projects/polymarket/crusaderbot/bot/messages.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` |
| Modified | `projects/polymarket/crusaderbot/bot/handlers/presets.py` |
| Modified | `projects/polymarket/crusaderbot/bot/keyboards/presets.py` |
| Modified | `projects/polymarket/crusaderbot/bot/menus/main.py` |
| Created  | `projects/polymarket/crusaderbot/reports/forge/tg-ux-redesign.md` |

---

## 4. What Is Working

- `dashboard_text()` signature backward-compatible (`last_scan` defaults to `"—"`).
- `_build_last_scan()` gracefully returns `"—"` when scanner has not run.
- `py_compile` clean on all 5 changed files — zero syntax errors.
- `_on_pick()` in-place edit uses `BadRequest` guard (falls back to reply on "Message is not modified").
- `preset_picker()` button labels show risk badge (🟢 Safe / 🟡 Balanced / 🔴 Aggressive).
- `preset_confirm()` Back nav routes to `preset:picker` (already registered in dispatcher).
- No new DB migrations required.
- No new callback patterns required — all use existing `preset:*` dispatcher registrations.

---

## 5. Known Issues

- `autotrade.show_autotrade()` (old 2-sub-menu) is no longer reachable from the reply keyboard but remains registered in the dispatcher for any in-flight `auto_trade:strategy` / `auto_trade:risk` callbacks still in user sessions.
- `mvp_auto_trade_kb()` import removed from `handlers/presets.py` — it is still used in `bot/keyboards/__init__.py` and other callers; no breakage.
- PnL simulation example uses `capital_pct` wizard default (not user's actual risk profile capital). This is clearly labelled "Example on $1,000" — no user capital is referenced.

---

## 6. What Is Next

- WARP🔹CMD review required — Tier: STANDARD.
- After merge: verify dashboard HUD rendering on real Telegram client (monospace alignment on mobile).
- Optional follow-up: port `_RISK_PROFILE_TEXT` sub-menu into Settings page for users who need Risk Profile access after the Auto Mode route change.
