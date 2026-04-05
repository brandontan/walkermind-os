# 10_11b_routing_fix

## 1. What was built

- Fixed Telegram callback routing by adding explicit deterministic handlers for `action:strategy` and `action:home` in the centralized callback router.
- Added dedicated callback-router helper methods (`render_strategy_view`, `render_home_view`) so routing intent is explicit and no unknown-action fallback is triggered for premium menu actions.
- Enforced reply keyboard action contract consistency with a required action list and startup-time validation for:
  - `trade`, `wallet`, `performance`, `exposure`, `strategy`, `home`.
- Removed legacy Telegram API routing layer files to eliminate conflicting parallel routing paths:
  - `projects/polymarket/polyquantbot/api/telegram/menu_router.py`
  - `projects/polymarket/polyquantbot/api/telegram/menu_handler.py`
- Removed stale test import dependency referencing the deleted legacy menu router.

## 2. Current system architecture

```text
Reply Keyboard click (text)
    ↓
main.py maps text via REPLY_MENU_MAP
    ↓
synthetic callback_query data = "action:{name}"
    ↓
telegram/handlers/callback_router.py (single source of truth)
    ↓
explicit action handlers (trade/wallet/performance/exposure/strategy/home)
    ↓
view renderers / handler screens
```

Single routing source is now `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py`.

## 3. Files created / modified (full paths)

- `projects/polymarket/polyquantbot/telegram/handlers/callback_router.py` (MODIFIED)
- `projects/polymarket/polyquantbot/telegram/ui/reply_keyboard.py` (MODIFIED)
- `projects/polymarket/polyquantbot/tests/test_phase115_system_validation.py` (MODIFIED: removed legacy import)
- `projects/polymarket/polyquantbot/api/telegram/menu_router.py` (DELETED)
- `projects/polymarket/polyquantbot/api/telegram/menu_handler.py` (DELETED)
- `projects/polymarket/polyquantbot/reports/forge/10_11b_routing_fix.md` (NEW)
- `PROJECT_STATE.md` (MODIFIED)

## 4. What is working

- All premium reply keyboard actions are mapped and represented in callback routing: `trade`, `wallet`, `performance`, `exposure`, `strategy`, `home`.
- `action:strategy` and `action:home` are now explicitly routed and no longer rely on unknown/fallback behavior.
- Legacy Telegram menu router/handler layer has been removed to prevent route conflicts and dual-source navigation behavior.
- Main polling flow remains consistent:
  - reply keyboard click → action extraction → `action:{name}` callback payload → callback router dispatch.

## 5. Known issues

- Local pytest async execution for callback-router tests is currently limited by environment plugin mismatch (`pytest-asyncio` not active in this runtime), so full async suite execution is blocked here.
- `docs/CLAUDE.md` is still missing at expected path from checklist.
- Live Telegram tap-through validation still requires bot token/chat runtime to verify visual output in Telegram client.

## 6. What is next

- Run SENTINEL validation for this routing-fix increment with live Telegram interaction checks across all six premium buttons.
- Confirm no legacy import/file references remain in CI static checks and full test environment.
- SENTINEL validation required for ui routing critical fix before merge.
  Source: `projects/polymarket/polyquantbot/reports/forge/10_11b_routing_fix.md`
