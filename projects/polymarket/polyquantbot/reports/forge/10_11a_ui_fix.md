# 10_11a_ui_fix

## 1) What was built

- Fixed HOME rendering fallback logic in `projects/polymarket/polyquantbot/interface/ui/views/home_view.py` so required keys (`balance`, `equity`, `positions`, `pnl`) always render using numeric defaults.
- Applied explicit fallback pattern for balance-equivalent values (`data.get("balance") or 0`) and equivalent defaults for equity/positions/exposure/PnL.
- Reordered HOME output so hero metric appears at the top as:
  - `📊 +0.00`
  - `Total PnL`
- Reduced HOME separator density to a maximum of 2 separators per screen.
- Updated `projects/polymarket/polyquantbot/interface/telegram/view_handler.py` with explicit action routing for:
  - `trade`
  - `wallet`
  - `performance`
  - `exposure`
  - `strategy`
  - `home`
- Updated `projects/polymarket/polyquantbot/telegram/ui/reply_keyboard.py` so `🧠 Strategy` maps to `action="strategy"` and the reply keyboard actions align with view handler route keys.

## 2) Current system architecture

```text
Reply Keyboard Press
   ↓
projects/polymarket/polyquantbot/telegram/ui/reply_keyboard.py
   ↓ (text → action mapping)
projects/polymarket/polyquantbot/main.py (synthetic callback action:*)
   ↓
projects/polymarket/polyquantbot/telegram/handlers/callback_router.py
   ↓ (data payload)
projects/polymarket/polyquantbot/interface/telegram/view_handler.py
   ↓
projects/polymarket/polyquantbot/interface/ui/views/home_view.py
```

Pipeline integrity remains unchanged:

`DATA → STRATEGY → INTELLIGENCE → RISK → EXECUTION → MONITORING`

## 3) Files created / modified (full paths)

Modified:
- `projects/polymarket/polyquantbot/interface/ui/views/home_view.py`
- `projects/polymarket/polyquantbot/interface/telegram/view_handler.py`
- `projects/polymarket/polyquantbot/telegram/ui/reply_keyboard.py`
- `PROJECT_STATE.md`

Created:
- `projects/polymarket/polyquantbot/reports/forge/10_11a_ui_fix.md`

## 4) What is working

- HOME now renders with non-empty numeric defaults for required fields instead of placeholder dashes in normal fallback cases.
- Hero PnL metric is rendered first in HOME.
- HOME now uses exactly two separators, reducing visual spam.
- View handler now has explicit `strategy` route and consistent key handling across primary actions.
- Reply keyboard action values now align with expected route keys and avoid `strategy_view`/`strategy` mismatch risk.

## 5) Known issues

- Full live-chat validation still depends on active Telegram credentials and runtime bot process.
- Historical non-primary action aliases outside the core menu may still exist in other legacy handlers but were not part of this targeted fix scope.

## 6) What is next

- Run SENTINEL validation for `10_11a_ui_fix` before merge.
- Execute dev Telegram smoke checks to confirm:
  - no `Unknown action`
  - no empty values for HOME core metrics
  - live payload values displayed in HOME/Trade/Wallet/Performance/Exposure/Strategy.
