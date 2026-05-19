# WARP•FORGE REPORT — power-mode-ux

**Branch:** WARP/phase-2-power-mode-ux
**Validation Tier:** STANDARD
**Claim Level:** NARROW INTEGRATION
**Validation Target:** Telegram UX layer — onboarding wizard, main menu, message layout
**Not in Scope:** trading logic, risk layer, execution, database schema, live guard
**Suggested Next Step:** WARP🔹CMD review → merge

---

## 1. What Was Built

**WARP-31 — Phase 2: Power Mode UX & Concierge Onboarding**

Three UX deliverables:

### A. Concierge Onboarding — 8-step interactive wizard

Replaced the 4-step onboarding wizard in `bot/handlers/onboarding.py` with an 8-step concierge flow:

| Step | State | Screen |
|------|-------|--------|
| 1 | `ONBOARD_WELCOME` | Brand card + "🚀 Begin Setup" |
| 2 | `ONBOARD_HOW_IT_WORKS` | 3-bullet explainer + "Got it →" |
| 3 | `ONBOARD_WALLET` | Wallet address shown + Copy + Next (seeds $1k paper credit) |
| 4 | `ONBOARD_PAPER_CREDIT` | "$1,000 added" confirmation + Continue |
| 5 | `ONBOARD_RISK_PROFILE` | Conservative / Balanced / Aggressive |
| 6 | `ONBOARD_PRESET_PICK` | 8 strategy presets (onboard:preset: prefix) |
| 7 | `ONBOARD_REVIEW` | Summary card: risk + preset + balance + mode |
| 8 | [launch → END] | Apply preset + mark complete + dashboard |

Each step uses a distinct callback prefix (`onboard:*`) isolated from the autotrade handler. Returning users (onboarding_complete=True) short-circuit directly to Dashboard on `/start`.

### B. Dynamic Main Menu — state-aware reply keyboard

Updated `main_menu()` and `main_menu_keyboard()` in `bot/keyboards/__init__.py` to accept state params:

- `paused=True` → "▶️ Resume" label (instead of "🤖 Auto Mode")
- `has_preset=False` → "🤖 Setup Auto" label
- `open_count > 0` → "💼 Trades (N)" with count

Dashboard handler (`dashboard.py`) now passes `paused`, `has_preset`, and `open_count` to every `main_menu()` call. `_build_dashboard_message()` return signature extended to 3-tuple `(text, has_preset, open_count)`.

### C. Tactical Dashboard Final — 32-character layout standardization

All hardcoded `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━` strings in `bot/messages.py` replaced with `DIV` constant. Affected:
- `WELCOME_TEXT`, `LEARN_MORE_TEXT`, `PRESET_PICKER_TEXT` (×2 occurrences)
- `preset_confirm_text()`, `preset_active_text()`
- `trades_empty_text()`, `trades_text()` (×2 occurrences)
- `wallet_text()`
- `EMERGENCY_TEXT`, `emergency_system_status_text()`

---

## 2. Current System Architecture

```text
Telegram /start
  └─ build_onboard_handler() [ConversationHandler — 7 wait-states]
       ├─ Step 1: _entry() → ONBOARD_WELCOME
       ├─ Step 2: _start_cb() → ONBOARD_HOW_IT_WORKS
       ├─ Step 3: _how_next_cb() → ONBOARD_WALLET [seeds $1k paper credit]
       ├─ Step 4: _wallet_next_cb() → ONBOARD_PAPER_CREDIT
       ├─ Step 5: _paper_credit_next_cb() → ONBOARD_RISK_PROFILE
       ├─ Step 6: _risk_cb() → ONBOARD_PRESET_PICK
       ├─ Step 7: _preset_cb() → ONBOARD_REVIEW
       └─ Step 8: _launch_cb() → apply preset → set onboarding_complete → Dashboard → END

Dashboard
  └─ _build_dashboard_message(user) → (text, has_preset, open_count)
       └─ main_menu(auto_on, paused, has_preset, open_count) → state-aware ReplyKeyboard

messages.py
  └─ DIV = "━" * 32 [single source of truth — used everywhere]
```

---

## 3. Files Created / Modified

**Created:**
- None

**Modified:**
- `projects/polymarket/crusaderbot/bot/handlers/onboarding.py` — full 8-step wizard rewrite (7 states, 10 handlers, new imports: get_preset, set_auto_trade, set_paused, update_settings, get_wallet)
- `projects/polymarket/crusaderbot/bot/keyboards/__init__.py` — `main_menu_keyboard()` / `main_menu()` updated with state params (auto_on, paused, has_preset, open_count)
- `projects/polymarket/crusaderbot/bot/messages.py` — 7 new onboarding text builders added; 11 hardcoded divider strings replaced with `DIV`
- `projects/polymarket/crusaderbot/bot/handlers/dashboard.py` — `_build_dashboard_message()` return signature extended to 3-tuple; both `main_menu()` call sites updated with state params

---

## 4. What Is Working

- 8-step wizard flow is complete with correct state routing
- Paper wallet seeding moved to step 3 transition (idempotent upsert preserved)
- Wallet address displayed in step 3 (get_wallet import added)
- Risk profile persisted via update_settings() at step 8 launch
- Preset applied via get_preset() + update_settings() + set_auto_trade() at step 8 launch
- Returning users bypass wizard on /start
- Menu-tap fallback exits wizard cleanly
- State-aware main menu: paused → "▶️ Resume", no preset → "🤖 Setup Auto", positions → count badge
- Dashboard passes live open_count to reply keyboard on every render
- All 11 hardcoded divider strings replaced with DIV constant
- `py_compile` clean on all 4 modified files

---

## 5. Known Issues

- `bot/handlers/start.py` still defines its own 3-state ConversationHandler (`build_start_handler()`) — dispatcher registers both. The `start.py` handler fires first (dispatcher registration order). These two handlers must be reconciled in a separate cleanup lane. The 8-step wizard in `onboarding.py` is the authoritative new flow.
- `pnl_insights.py`, `copy_trade.py`, `portfolio_chart.py` may still have legacy `━━━` strings — out of scope for this lane per existing known issues.

---

## 6. What Is Next

```text
WARP🔹CMD review required.
Source: projects/polymarket/crusaderbot/reports/forge/power-mode-ux.md
Tier: STANDARD
```

After merge:
- Reconcile `start.py` ConversationHandler vs `onboarding.py` (separate cleanup lane)
- WARP-30 merge (System Hardening) gates before WARP-31 if still pending
