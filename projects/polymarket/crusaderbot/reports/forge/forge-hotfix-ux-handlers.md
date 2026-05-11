# WARP•FORGE Report — Hotfix: Legacy UX Handler Cleanup

**Branch:** WARP/HOTFIX-UX-OVERHAUL-HANDLERS
**Validation Tier:** STANDARD
**Claim Level:** PRESENTATION
**SENTINEL Required:** NO
**Date:** 2026-05-12

---

## 1. What Was Built

Removed legacy Telegram text-input handlers and fixed strategy display names left over from pre-UX-Overhaul code paths. PR #989 introduced new button-driven flows but did not remove the old handlers, creating a race condition where the old `setup:capital` and `setup:tpsl` callbacks could still set awaiting-text state and prompt users with legacy plain-text prompts.

**Fix 1 — Removed legacy TP/SL text-input handler**
Deleted the `elif sub == "tpsl"` branch in `setup_callback` that set `awaiting="tpsl"` and sent "Enter `TP SL` as two percentages separated by a space." Also deleted the corresponding `elif awaiting == "tpsl"` handler in `text_input` that parsed "15 8"-style two-integer space-separated input. The new settings flow uses `tp_set:` / `sl_set:` callbacks via `tp_set_callback` / `sl_set_callback` (registered in dispatcher, unaffected).

**Fix 2 — Removed legacy Capital text-input handler**
Deleted the `elif sub == "capital"` branch in `setup_callback` that set `awaiting="capital_pct"` and sent "Enter capital allocation percentage...Send the number now." The `capital_pct` handler in `text_input` is retained because it is still used by the new `cap_set:custom` preset flow (user taps Custom → types a number → `text_input` handles it).

**Fix 3 — Strategy display name mapping**
Added `STRATEGY_DISPLAY_NAMES` dict in `setup.py`. Applied to:
- `setup_legacy_root` status text (was `', '.join(s['strategy_types'])` → shows raw internal names)
- `dashboard.py` preset label in the main dashboard card (was `s.replace("_", " ").title()` → "Value" instead of "Edge Finder")
- `dashboard.py` `sub == "autotrade"` status text (same raw-join fix)

**Fix 4 — Zero legacy prompts verified**
Grep confirmed zero occurrences of: "separated by a space", "Send the number now", "Enter TP SL", "Enter capital allocation percentage", "Send skip to clear", "Enter your".

**Fix 5 — Dispatcher dedup verified**
`tp_set_callback`, `sl_set_callback`, `cap_set_callback`, `set_strategy_card` each registered exactly once. No ConversationHandler state overlap. `setup:*` callback handler retained (still handles `setup:risk`, `setup:categories`, `setup:mode`, `setup:redeem`, `setup:copy`).

**Test fixes (3 existing tests updated)**
- `test_my_trades_renders_with_positions`: added `get_settings_for` mock (handler now fetches TP/SL from settings)
- `test_my_trades_renders_empty_state`: same
- `test_format_positions_section_hierarchy`: updated assertions to match new UX format (`@ $0.420` not `at $0.42`; `TP: — | SL: —` not `$5.00`)

---

## 2. Current System Architecture

```
Settings Hub (⚙️)
  └─ 🎯 TP/SL → settings:tpsl → tp_preset_kb → tp_set:<N> → tp_set_callback
                                                → sl_set:<N> → sl_set_callback
                              → tp_set:custom → awaiting=tpsl_tp → settings_text_input
  └─ 💵 Capital → settings:capital → capital_preset_kb → cap_set:<N> → cap_set_callback
                                   → cap_set:custom → awaiting=capital_pct → setup.text_input

Auto-Trade (🤖)
  └─ setup_root → strategy_card_kb → strategy:<card> → set_strategy_card
                                   → stores backend name(s) via update_settings
                                   → confirm shows STRATEGY_DISPLAY_NAMES[card]

Dashboard
  └─ preset string: STRATEGY_DISPLAY_NAMES.get(s, fallback) for each strategy_type
  └─ autotrade status: STRATEGY_DISPLAY_NAMES.get(t, t) for each strategy_type
```

---

## 3. Files Created / Modified

**Modified:**
- `projects/polymarket/crusaderbot/bot/handlers/setup.py`
  - Added `STRATEGY_DISPLAY_NAMES` constant (lines after logger init)
  - Removed `elif sub == "capital"` block from `setup_callback`
  - Removed `elif sub == "tpsl"` block from `setup_callback`
  - Removed `elif awaiting == "tpsl"` block from `text_input`
  - Fixed `setup_legacy_root` strategy display to use `STRATEGY_DISPLAY_NAMES`

- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py`
  - Added `from .setup import STRATEGY_DISPLAY_NAMES`
  - Fixed preset label in dashboard card to use `STRATEGY_DISPLAY_NAMES`
  - Fixed autotrade status text to use `STRATEGY_DISPLAY_NAMES`

- `projects/polymarket/crusaderbot/tests/test_phase5i_my_trades.py`
  - Tests 1, 2: added `get_settings_for` mock (new handler dependency)
  - Test 10: updated assertions to match new UX card format; passed `tp_pct=None, sl_pct=None`

**Not Modified:**
- `bot/dispatcher.py` — no duplicate registrations found; no changes needed
- `bot/keyboards/settings.py` — no changes needed
- `bot/handlers/settings.py` — no changes needed
- Any trading, risk, or execution code

---

## 4. What Is Working

- `settings:tpsl` → preset buttons (Step 1 TP, Step 2 SL) — no text prompt
- `settings:capital` → preset buttons with live dollar amounts — no text prompt
- `cap_set:custom` → still works via `text_input` for custom percentage entry
- Strategy names display as "Signal", "Edge Finder", "Momentum Reversal", "All Strategies"
- 99 hermetic tests green (44 UX overhaul + 13 my_trades + 21 pnl_insights + 21 phase5d grid)

---

## 5. Known Issues

None introduced by this hotfix. `setup:capital` and `setup:tpsl` paths in `setup_callback` are now silent no-ops if somehow triggered (e.g., old keyboard still in a user's chat history) — they fall through without side effects.

---

## 6. What Is Next

- WARP🔹CMD review → merge
- No follow-up tasks required from this hotfix

---

**Validation Target:** Legacy text-prompt handlers in `setup.py`; strategy display sites in `setup.py` and `dashboard.py`
**Not in Scope:** New features, trading logic, DB schema, activation guards
**Suggested Next Step:** WARP🔹CMD review → merge to main
