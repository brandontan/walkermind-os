# WARP•FORGE Report — customize-wizard

**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION — ConversationHandler wizard + DB update
**Validation Target:** 5-step Auto-Trade customize wizard (capital, TP, SL, skip, review)
**Not in Scope:** Copy Trade handlers, execution engine, activation guards, DB schema, preset default values
**Suggested Next Step:** WARP🔹CMD review

---

## 1. What Was Built

5-step ConversationHandler wizard that allows users to override individual
Auto-Trade preset settings (capital allocation, take-profit, stop-loss) before
activating a preset or while a preset is already active.

Entry points:
- Confirmation card → **Customize** button (`preset:customize:{key}`) — activates preset with custom config on Save
- Status card → **Edit Config** button (`preset:edit`) — updates settings without re-activating on Save

Wizard flow:
- Step 1/5 — Capital Allocation: 4 preset buttons (25 / 50 / 75 / 100%) + Cancel
- Step 2/5 — Take Profit: 4 preset buttons (+10 / +15 / +20 / +30%) + Custom + Back
- Step 3/5 — Stop Loss: 4 preset buttons (-5 / -8 / -10 / -15%) + Custom + Back
- Step 4/5 — Copy Targets: auto-skipped for all current presets (signal_sniper, value_hunter, full_auto)
- Step 5/5 — Review: hierarchy card (Preset / Capital / TP / SL / Mode) + Save + Back

Save behaviour:
- New activation path: calls `update_settings` with all preset + custom fields, then `set_auto_trade(True)` + `set_paused(False)`
- Edit-only path: calls `update_settings` with capital_alloc_pct + tp_pct + sl_pct only (no activation guard touched)
- Clears wizard state from `ctx.user_data` and shows success message + [Dashboard] [Auto-Trade] buttons

Custom input (TP and SL):
- Sends current-step message with a Back button
- Validates: numeric only; TP bounds 1–200; SL bounds 1–50
- Invalid input sends error message and stays in `CUSTOM_INPUT` state
- Valid input advances to next step

Global handlers:
- `/menu` command exits wizard and calls the main menu handler
- Main-menu button tap (📊🐋🤖📈💰🚨) exits wizard and routes to the correct surface
- Cancel button at every step exits wizard and keeps original preset defaults

---

## 2. Current System Architecture

```
Telegram Bot
  └── dispatcher.py
        ├── presets.build_customize_handler()   ← NEW (registered before ^preset:)
        │     entry: preset:customize:{key}, preset:edit
        │     states: CUSTOM_CAPITAL → CUSTOM_TP → CUSTOM_SL → CUSTOM_REVIEW
        │             CUSTOM_INPUT (shared TP/SL custom text entry)
        │     fallbacks: /menu, main-menu buttons, plain text
        └── preset_callback (^preset:)          ← unchanged
```

Wizard data is stored in `ctx.user_data["customize_wz"]` (distinct key from
copy_trade's `ctx.user_data["wizard"]` to avoid cross-wizard contamination).

DB write path (unchanged columns):
- `user_settings.capital_alloc_pct`
- `user_settings.tp_pct`
- `user_settings.sl_pct`
- `user_settings.active_preset` (new-activation path only)
- `user_settings.strategy_types` (new-activation path only)
- `user_settings.max_position_pct` (new-activation path only)
- `users.auto_trade_on` (new-activation path only)
- `users.paused` (new-activation path only)

---

## 3. Files Created / Modified

| Path | Change |
|---|---|
| `projects/polymarket/crusaderbot/bot/keyboards/presets.py` | Added 6 wizard keyboard functions |
| `projects/polymarket/crusaderbot/bot/handlers/presets.py` | Added wizard state constants, helpers, 15 handler functions, `build_customize_handler()` |
| `projects/polymarket/crusaderbot/bot/dispatcher.py` | Registered `presets.build_customize_handler()` before `^preset:` handler |
| `projects/polymarket/crusaderbot/tests/test_phase5g_customize_wizard.py` | Created — 22 hermetic tests |

---

## 4. What Is Working

- Full 5-step wizard flow: capital → TP → SL → (skip step 4) → review → save
- All buttons render as 2-column grids via existing `grid_rows()` helper
- Custom input for TP (1–200) and SL (1–50) with validation and error feedback
- Back navigation: review → SL → TP → capital; custom-input → previous step
- Cancel at every step clears state and shows "cancelled" message
- Save (new activation) writes all preset fields + flips auto_trade_on
- Save (edit-only) writes only capital/TP/SL without touching activation guards
- Global menu intercept exits wizard cleanly and routes to the correct surface
- ConversationHandler registered before `^preset:` so `preset:customize:*` and `preset:edit` are intercepted correctly
- `ENABLE_LIVE_TRADING` guard not touched — activation stays paper-only via existing guard in `_on_activate`
- 22/22 hermetic tests pass

---

## 5. Known Issues

None. Wizard is self-contained; no new runtime dependencies introduced.

---

## 6. What Is Next

WARP🔹CMD review required.
Source: `projects/polymarket/crusaderbot/reports/forge/customize-wizard.md`
Tier: STANDARD
